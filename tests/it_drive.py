"""
Test integracyjny etapu 6 — narzędzia Drive.

UWAGA: Tuta Drive to funkcja beta dostępna tylko dla płatnych kont.
Konto testowe your@tuta.com (darmowe) nie ma Drive — test zostanie
pominięty z komunikatem. Uruchom na płatnym koncie (np. owner@tuta.com).

Scenariusze (wymaga Drive):
 1. list "/" — zawartość roota
 2. mkdir — utwórz folder testowy
 3. upload — wgraj plik
 4. list folderu — zweryfikuj że plik widoczny
 5. download — pobierz plik i sprawdź zgodność
 6. rename — zmień nazwę pliku
 7. move — przenieś do podfolderu
 8. delete (trash) — przenieś do kosza
 9. Sprzątanie

Uruchamianie:
    TUTA_EMAIL=... TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_drive.py
"""

import asyncio
import os
import sys
import hashlib
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_drive import (
    _normalize_path, _split_path, _DrivePathCache
)


def _unit_tests():
    """Testy pomocnicze (bez sieci)."""
    print("=== Test 0: unit testy helpers ===")
    assert _normalize_path("") == "/"
    assert _normalize_path("/") == "/"
    assert _normalize_path("Documents") == "/Documents"
    assert _normalize_path("/Documents/") == "/Documents"
    assert _normalize_path("//Documents//2024//") == "/Documents/2024"
    print("  OK: _normalize_path")

    assert _split_path("/") == ("/", "")
    assert _split_path("/Documents") == ("/", "Documents")
    assert _split_path("/Documents/2024") == ("/Documents", "2024")
    assert _split_path("/a/b/c.pdf") == ("/a/b", "c.pdf")
    print("  OK: _split_path")


async def run_tests() -> None:
    _unit_tests()
    print()

    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_DRIVE", "1")
    env.setdefault("TUTAMCP_ENABLE_MAIL", "0")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test Drive (etap 6) ===\n")

    # Sprawdź dostępność Drive
    from tuta.api import TutaAPIError

    async def _check_drive(client, session):
        try:
            group_id, group_key, key_version = await client.get_drive_group_key(session)
            return group_id, group_key, key_version
        except TutaAPIError as e:
            if "groupType=7" in str(e):
                return None, None, None
            raise

    result = await sm.call(_check_drive)
    group_id, group_key, key_version = result

    if group_id is None:
        print("  SKIP: Tuta Drive niedostępny dla tego konta (wymagane konto płatne)")
        print("  Uruchom na koncie płatnym (np. owner@tuta.com)")
        await sm.close()
        print("\n=== Testy Drive POMINIĘTE (brak Drive) ===")
        return

    print(f"  Drive dostępny: group_id={group_id[:12]}...")

    # Pobierz root — 412 oznacza że konto ma stub membership ale Drive nie jest włączone
    async def _get_root(client, session):
        try:
            return await client.get_drive_root(session, group_id, group_key, key_version)
        except TutaAPIError as e:
            if e.status_code in (412, 403):
                return None, None
            raise

    root_result = await sm.call(_get_root)
    root_id, trash_id = root_result
    if root_id is None:
        print("  SKIP: Drive group istnieje, ale root niedostępny (412/403)")
        print("  Konto prawdopodobnie ma stub membership bez aktywnego Drive.")
        print("  Uruchom na płatnym koncie z aktywnym Drive.")
        await sm.close()
        print("\n=== Testy Drive POMINIĘTE (root niedostępny) ===")
        return
    print(f"  root_id={root_id}, trash_id={trash_id}")

    # ── Test 1: list root ────────────────────────────────────────────────────
    print("\n=== Test 1: list root ===")
    from tutamcp.tools_drive import _DrivePathCache, _resolve_folder_path

    cache = _DrivePathCache()
    cache.set_root(root_id, trash_id)

    async def _list_root(client, session):
        return await client.list_drive_folder_contents(session, group_key, root_id)

    subfolders, files = await sm.call(_list_root)
    print(f"  Root: {len(subfolders)} podfolderów, {len(files)} plików")
    for f in subfolders:
        print(f"  [folder] {f.name!r} id={f.id_tuple}")
    for f in files:
        print(f"  [file]   {f.name!r} ({f.size} B)")
    print("  OK")

    # ── Test 2: mkdir ────────────────────────────────────────────────────────
    print("\n=== Test 2: mkdir /tutamcp-test ===")

    async def _mkdir(client, session):
        return await client.create_drive_folder_api(
            session, group_key, key_version, "tutamcp-test", root_id
        )

    test_folder = await sm.call(_mkdir)
    print(f"  Folder: {test_folder.name!r} id={test_folder.id_tuple}")
    test_folder_id = test_folder.id_tuple

    # Weryfikuj
    subfolders2, _ = await sm.call(_list_root)
    found = any(f.name == "tutamcp-test" for f in subfolders2)
    assert found, "Folder testowy nie widoczny w root"
    print("  OK: folder widoczny w root")

    # ── Test 3: upload ───────────────────────────────────────────────────────
    print("\n=== Test 3: upload test file ===")
    test_content = b"Hello from tutamcp test! " + b"x" * 100
    test_filename = "tutamcp_test.txt"

    async def _upload(client, session):
        return await client.upload_drive_file_api(
            session, group_id, group_key, key_version,
            test_filename, "text/plain", test_content, test_folder_id
        )

    uploaded = await sm.call(_upload)
    print(f"  Plik: {uploaded.name!r} ({uploaded.size} B) id={uploaded.id_tuple}")

    # ── Test 4: list folderu testowego ───────────────────────────────────────
    print("\n=== Test 4: list /tutamcp-test ===")

    async def _list_test_folder(client, session):
        return await client.list_drive_folder_contents(session, group_key, test_folder_id)

    sub2, files2 = await sm.call(_list_test_folder)
    found_file = next((f for f in files2 if f.name == test_filename), None)
    assert found_file is not None, f"Plik {test_filename!r} nie widoczny"
    print(f"  OK: {found_file.name!r} ({found_file.size} B)")

    # ── Test 5: download ─────────────────────────────────────────────────────
    print("\n=== Test 5: download ===")

    async def _download(client, session):
        return await client.download_drive_file_data(session, group_key, found_file)

    downloaded_data = await sm.call(_download)
    assert downloaded_data == test_content, \
        f"Dane po download różnią się: got {len(downloaded_data)} B, exp {len(test_content)} B"
    md5_orig = hashlib.md5(test_content).hexdigest()
    md5_dl = hashlib.md5(downloaded_data).hexdigest()
    assert md5_orig == md5_dl, f"MD5 mismatch: {md5_orig} vs {md5_dl}"
    print(f"  OK: {len(downloaded_data)} B, MD5={md5_dl}")

    # ── Test 6: rename ───────────────────────────────────────────────────────
    print("\n=== Test 6: rename ===")

    async def _rename(client, session):
        await client.rename_drive_item_api(
            session, group_key, found_file.raw, "tutamcp_test_renamed.txt", is_file=True
        )

    await sm.call(_rename)

    _, files3 = await sm.call(_list_test_folder)
    renamed = next((f for f in files3 if f.name == "tutamcp_test_renamed.txt"), None)
    assert renamed is not None, "Zmieniona nazwa pliku nie widoczna"
    print(f"  OK: {renamed.name!r}")

    # ── Test 7: move (do trash) ──────────────────────────────────────────────
    print("\n=== Test 7: delete folder (do kosza) ===")

    async def _delete_folder(client, session):
        await client.delete_drive_items_api(
            session, [], [test_folder_id], permanent=False
        )

    await sm.call(_delete_folder)

    subfolders3, _ = await sm.call(_list_root)
    still_there = any(f.id_tuple == test_folder_id for f in subfolders3)
    assert not still_there, "Folder testowy nadal w root po przeniesieniu do kosza"
    print("  OK: folder przeniesiony do kosza")

    await sm.close()
    print("\n=== Wszystkie testy Drive PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
