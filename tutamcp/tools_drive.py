"""
Narzędzia MCP dla Tuta Drive.

Rejestrowane warunkowo gdy TUTAMCP_ENABLE_DRIVE=1.
Wymaga płatnego konta Tuta (Drive to funkcja beta dostępna wyłącznie dla
kont płatnych — darmowe konta nie mają groupType=7 i zwrócą błąd przy starcie).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from typing import Any, Optional

from tutamcp.errors import safe_call as _safe_call, tuta_api_error_to_dict as _api_err

logger = logging.getLogger(__name__)

# Limit rozmiaru pliku do pobrania/uploadu (512 MB)
_MAX_FILE_BYTES = 512 * 1024 * 1024

_DRIVE_UNAVAILABLE_MSG = "Tuta Drive niedostępny dla tego konta (wymagane konto płatne)"


def _is_drive_unavailable(e: Exception) -> bool:
    """Sprawdza czy wyjątek oznacza brak dostępu do Drive (nie błąd logiczny)."""
    msg = str(e)
    return "groupType=7" in msg or "Brak grupy Drive" in msg or getattr(e, "status_code", 0) in (412, 403)


class _DrivePathCache:
    """
    Pamięć podręczna mapowania ścieżka→id_tuple dla folderów Drive.
    Inwalidowana przy operacjach zapisu (mkdir, upload, rename, move, delete).
    """

    def __init__(self):
        self._cache: dict[str, list] = {}
        self._root_id: Optional[list] = None
        self._trash_id: Optional[list] = None

    def set_root(self, root_id: list, trash_id: list) -> None:
        self._root_id = root_id
        self._trash_id = trash_id
        self._cache["/"] = root_id
        self._cache["/.trash"] = trash_id

    def get(self, path: str) -> Optional[list]:
        return self._cache.get(_normalize_path(path))

    def put(self, path: str, id_tuple: list) -> None:
        self._cache[_normalize_path(path)] = id_tuple

    def invalidate(self) -> None:
        """Czyści cache po operacjach zapisu."""
        saved_root = self._root_id
        saved_trash = self._trash_id
        self._cache.clear()
        if saved_root:
            self.set_root(saved_root, saved_trash)


def _normalize_path(path: str) -> str:
    """Normalizuje ścieżkę: usuwa podwójne slashe, trailing slash."""
    if not path:
        return "/"
    p = "/" + "/".join(part for part in path.split("/") if part)
    return p or "/"


def _split_path(path: str) -> tuple[str, str]:
    """Dzieli ścieżkę na (katalog_nadrzędny, nazwa_elementu)."""
    norm = _normalize_path(path)
    if norm == "/":
        return "/", ""
    parent = "/" + "/".join(norm.strip("/").split("/")[:-1])
    name = norm.split("/")[-1]
    return _normalize_path(parent), name


async def _get_drive_info(client, session) -> tuple:
    """Zwraca (group_id, group_key, key_version, root_id, trash_id)."""
    group_id, group_key, key_version = await client.get_drive_group_key(session)
    root_id, trash_id = await client.get_drive_root(session, group_id, group_key, key_version)
    return group_id, group_key, key_version, root_id, trash_id


async def _resolve_folder_path(
    path: str,
    client,
    session,
    group_key: bytes,
    root_id: list,
    cache: _DrivePathCache,
) -> Optional[list]:
    """
    Resolves ścieżkę folderu do id_tuple.
    Idzie rekurencyjnie od roota, keszując wyniki.
    Zwraca None gdy folder nie istnieje.
    """
    norm = _normalize_path(path)
    if norm == "/":
        return root_id

    cached = cache.get(norm)
    if cached:
        return cached

    parts = [p for p in norm.split("/") if p]
    current_id = root_id
    current_path = ""

    for part in parts:
        current_path = f"{current_path}/{part}"
        cached = cache.get(current_path)
        if cached:
            current_id = cached
            continue
        # Przeszukaj zawartość folderu
        subfolders, _ = await client.list_drive_folder_contents(session, group_key, current_id)
        found = next((f.id_tuple for f in subfolders if f.name == part), None)
        if found is None:
            return None
        cache.put(current_path, found)
        current_id = found

    return current_id


async def _find_item_by_path(
    path: str,
    client,
    session,
    group_key: bytes,
    root_id: list,
    cache: _DrivePathCache,
) -> tuple[Optional[Any], bool]:
    """
    Szuka pliku lub folderu po ścieżce.
    Zwraca (item, is_file) — item to DriveFile lub DriveFolder.
    Gdy nie znaleziono: (None, False).
    """
    parent_path, name = _split_path(path)
    if not name:
        return None, False

    parent_id = await _resolve_folder_path(parent_path, client, session, group_key, root_id, cache)
    if parent_id is None:
        return None, False

    subfolders, files = await client.list_drive_folder_contents(session, group_key, parent_id)

    for f in files:
        if f.name == name:
            return f, True
    for f in subfolders:
        if f.name == name:
            return f, False
    return None, False


def _folder_to_dict(f) -> dict:
    return {
        "type": "folder",
        "name": f.name,
        "id": f.id_tuple,
        "folder_type": f.folder_type,
        "created_ms": f.created_ms,
        "updated_ms": f.updated_ms,
    }


def _file_to_dict(f) -> dict:
    return {
        "type": "file",
        "name": f.name,
        "size": f.size,
        "mime_type": f.mime_type,
        "id": f.id_tuple,
        "created_ms": f.created_ms,
        "updated_ms": f.updated_ms,
    }


def register_drive_tools(mcp, cfg, sm) -> None:
    """Rejestruje narzędzia Drive w serwerze FastMCP."""

    _cache = _DrivePathCache()

    @mcp.tool()
    async def tuta_drive_list(path: str = "/") -> dict[str, Any]:
        """
        Lists contents of a Tuta Drive folder.

        Parameters:
        - path: Folder path (default: "/" for root). Examples: "/", "/Documents", "/Projects/2024".

        Returns lists of folders and files with: name, id, size (files), mime_type (files),
        created_ms, updated_ms.

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        async def _list(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            folder_id = await _resolve_folder_path(path, client, session, group_key, root_id, _cache)
            if folder_id is None:
                return None, None
            subfolders, files = await client.list_drive_folder_contents(session, group_key, folder_id)
            return subfolders, files

        try:
            result = await sm.call(_list)
        except Exception as e:
            if "groupType=7" in str(e) or "Drive" in str(e) or _is_drive_unavailable(e):
                return {"error": "Tuta Drive niedostępny dla tego konta (wymagane konto płatne)"}
            raise

        subfolders, files = result
        if subfolders is None:
            return {"error": f"Folder nie znaleziony: {path!r}"}

        return {
            "path": _normalize_path(path),
            "folders": [_folder_to_dict(f) for f in subfolders],
            "files": [_file_to_dict(f) for f in files],
            "count": len(subfolders) + len(files),
        }

    @mcp.tool()
    async def tuta_drive_download(
        path: str,
        filename: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Downloads a file from Tuta Drive to the local download directory.

        Parameters:
        - path:     Full path to the file in Drive, e.g. "/Documents/report.pdf".
        - filename: Override the local filename (optional, defaults to original name).

        Returns: local_path, size, md5 of the downloaded file.
        Limit: files larger than 512 MB are rejected.

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        async def _download(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            item, is_file = await _find_item_by_path(path, client, session, group_key, root_id, _cache)
            if item is None:
                return None, "Plik nie znaleziony: " + repr(path)
            if not is_file:
                return None, f"Ścieżka {path!r} wskazuje na folder, nie plik"
            if item.size > _MAX_FILE_BYTES:
                return None, f"Plik za duży: {item.size / 1024 / 1024:.1f} MB > 512 MB"
            data = await client.download_drive_file_data(session, group_key, item)
            return item, data

        try:
            result = await sm.call(_download)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        item, data = result
        if item is None:
            return {"error": data}

        # Zapisz do TUTAMCP_DOWNLOAD_DIR
        dl_dir = cfg.download_dir
        os.makedirs(dl_dir, exist_ok=True)

        import re
        safe_name = os.path.basename(filename or item.name)
        # Sanityzacja: usuń znaki poza dozwolonymi, zablokuj path traversal
        safe_name = re.sub(r"[^\w\s\-\.\(\)\[\]@#$%^&+=!,]", "_", safe_name)
        # ".." i "." po sanityzacji to nadal traversal; zastąp podkreślnikiem
        safe_name = safe_name.strip(".")
        if not safe_name:
            safe_name = "drive_download"

        local_path = os.path.join(dl_dir, safe_name)
        with open(local_path, "wb") as f:
            f.write(data)

        md5 = hashlib.md5(data).hexdigest()
        logger.info("tuta_drive_download: %r → %s (%d B)", path, local_path, len(data))
        return {
            "status": "downloaded",
            "local_path": local_path,
            "size": len(data),
            "md5": md5,
            "original_name": item.name,
            "mime_type": item.mime_type,
        }

    @mcp.tool()
    async def tuta_drive_mkdir(path: str) -> dict[str, Any]:
        """
        Creates a new folder in Tuta Drive.

        Parameters:
        - path: Full path of the folder to create, e.g. "/Documents/NewFolder".
                The parent folder must already exist.

        Returns the new folder's id_tuple.

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        parent_path, name = _split_path(path)
        if not name:
            return {"error": "Nieprawidłowa ścieżka — brak nazwy folderu"}

        async def _mkdir(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            parent_id = await _resolve_folder_path(parent_path, client, session, group_key, root_id, _cache)
            if parent_id is None:
                return None, f"Folder nadrzędny nie istnieje: {parent_path!r}"
            folder = await client.create_drive_folder_api(session, group_key, key_version, name, parent_id)
            return folder, None

        try:
            result = await sm.call(_mkdir)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        folder, err = result
        if folder is None:
            return {"error": err}

        _cache.invalidate()
        logger.info("tuta_drive_mkdir: %r → %s", path, folder.id_tuple)
        return {
            "status": "created",
            "path": _normalize_path(path),
            "id": folder.id_tuple,
        }

    @mcp.tool()
    async def tuta_drive_upload(
        local_path: str,
        drive_path: str,
    ) -> dict[str, Any]:
        """
        Uploads a local file to Tuta Drive.

        Parameters:
        - local_path: Absolute path to the local file to upload.
        - drive_path: Destination path in Drive, e.g. "/Documents/report.pdf".
                      The parent folder must already exist.
                      The last path component is the filename in Drive.

        Limit: files larger than 512 MB are rejected.

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        if not os.path.isfile(local_path):
            return {"error": f"Plik lokalny nie istnieje: {local_path!r}"}

        file_size = os.path.getsize(local_path)
        if file_size > _MAX_FILE_BYTES:
            return {"error": f"Plik za duży: {file_size / 1024 / 1024:.1f} MB > 512 MB"}

        parent_path, drive_name = _split_path(drive_path)
        if not drive_name:
            drive_name = os.path.basename(local_path)

        mime = mimetypes.guess_type(drive_name)[0] or "application/octet-stream"

        with open(local_path, "rb") as f:
            data = f.read()

        async def _upload(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            parent_id = await _resolve_folder_path(parent_path, client, session, group_key, root_id, _cache)
            if parent_id is None:
                return None, f"Folder docelowy nie istnieje: {parent_path!r}"
            drive_file = await client.upload_drive_file_api(
                session, group_id, group_key, key_version, drive_name, mime, data, parent_id
            )
            return drive_file, None

        try:
            result = await sm.call(_upload)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        drive_file, err = result
        if drive_file is None:
            return {"error": err}

        _cache.invalidate()
        logger.info("tuta_drive_upload: %r → %r (%d B)", local_path, drive_path, len(data))
        return {
            "status": "uploaded",
            "drive_path": _normalize_path(drive_path),
            "id": drive_file.id_tuple,
            "size": drive_file.size,
            "mime_type": drive_file.mime_type,
        }

    @mcp.tool()
    async def tuta_drive_rename(
        path: str,
        new_name: str,
    ) -> dict[str, Any]:
        """
        Renames a file or folder in Tuta Drive.

        Parameters:
        - path:     Full path to the item to rename, e.g. "/Documents/old_name.pdf".
        - new_name: New name (just the name, not a path), e.g. "new_name.pdf".

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        if "/" in new_name:
            return {"error": "new_name nie może zawierać '/'. Użyj tuta_drive_move do przenoszenia."}
        if not new_name.strip():
            return {"error": "Nowa nazwa nie może być pusta"}

        async def _rename(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            item, is_file = await _find_item_by_path(path, client, session, group_key, root_id, _cache)
            if item is None:
                return f"Element nie znaleziony: {path!r}"
            raw = item.raw
            await client.rename_drive_item_api(session, group_key, raw, new_name, is_file)
            return None

        try:
            err = await sm.call(_rename)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        if err:
            return {"error": err}

        _cache.invalidate()
        parent_path, _ = _split_path(path)
        new_path = _normalize_path(f"{parent_path}/{new_name}")
        logger.info("tuta_drive_rename: %r → %r", path, new_path)
        return {"status": "renamed", "old_path": _normalize_path(path), "new_path": new_path}

    @mcp.tool()
    async def tuta_drive_move(
        path: str,
        dest_folder: str,
    ) -> dict[str, Any]:
        """
        Moves a file or folder to a different folder in Tuta Drive.

        Parameters:
        - path:        Full path to the item to move, e.g. "/Documents/report.pdf".
        - dest_folder: Destination folder path, e.g. "/Archive/2024".
                       The destination folder must already exist.

        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        async def _move(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)

            item, is_file = await _find_item_by_path(path, client, session, group_key, root_id, _cache)
            if item is None:
                return f"Element nie znaleziony: {path!r}"

            dest_id = await _resolve_folder_path(dest_folder, client, session, group_key, root_id, _cache)
            if dest_id is None:
                return f"Folder docelowy nie istnieje: {dest_folder!r}"

            if is_file:
                await client.move_drive_items_api(session, group_key, [item], [], dest_id)
            else:
                await client.move_drive_items_api(session, group_key, [], [item], dest_id)
            return None

        try:
            err = await sm.call(_move)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        if err:
            return {"error": err}

        _cache.invalidate()
        _, name = _split_path(path)
        new_path = _normalize_path(f"{dest_folder}/{name}")
        logger.info("tuta_drive_move: %r → %r", path, new_path)
        return {"status": "moved", "old_path": _normalize_path(path), "new_path": new_path}

    @mcp.tool()
    async def tuta_drive_delete(
        path: str,
        permanent: bool = False,
    ) -> dict[str, Any]:
        """
        Deletes a file or folder from Tuta Drive.

        Parameters:
        - path:      Full path to the item to delete, e.g. "/Documents/old_report.pdf".
        - permanent: False (default) = move to Trash; True = permanent delete (no recovery).

        Note: Deleting a folder moves/deletes all its contents recursively.
        Note: Tuta Drive is a paid feature (beta). Returns an error for free accounts.
        """
        async def _delete(client, session):
            group_id, group_key, key_version, root_id, trash_id = await _get_drive_info(client, session)
            if not _cache._root_id:
                _cache.set_root(root_id, trash_id)
            item, is_file = await _find_item_by_path(path, client, session, group_key, root_id, _cache)
            if item is None:
                return f"Element nie znaleziony: {path!r}"
            if is_file:
                await client.delete_drive_items_api(session, [item.id_tuple], [], permanent=permanent)
            else:
                await client.delete_drive_items_api(session, [], [item.id_tuple], permanent=permanent)
            return None

        try:
            err = await sm.call(_delete)
        except Exception as e:
            if _is_drive_unavailable(e):
                return {"error": _DRIVE_UNAVAILABLE_MSG}
            try:
                from tuta.api import TutaAPIError
                if isinstance(e, TutaAPIError):
                    return _api_err(e)
            except ImportError:
                pass
            raise

        if err:
            return {"error": err}

        _cache.invalidate()
        action = "deleted permanently" if permanent else "moved to trash"
        logger.info("tuta_drive_delete: %r (%s)", path, action)
        return {
            "status": action,
            "path": _normalize_path(path),
        }
