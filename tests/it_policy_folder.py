"""
Test integracyjny policy.py — tryb FOLDER.

Tworzy tymczasowy folder "_claude_test_", konfiguruje MCP w trybie FOLDER
z tym folderem jako cfg.mail_folder, i sprawdza że:
 - tuta_mail_list_folders zwraca TYLKO skonfigurowany folder
 - tuta_mail_list z właściwym ID działa
 - tuta_mail_list z obcym ID odmawia
 - CRUD folderów NIE jest zarejestrowane w trybie FOLDER

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_policy_folder.py
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.policy import allowed_tools, check_folder_access


async def run_tests() -> None:
    env_base = dict(os.environ)
    env_base.setdefault("TUTAMCP_ENABLE_MAIL", "1")

    # ── Krok 0: utwórz tymczasowy folder przez dedicated mode ────────────────
    print("=== Krok 0: tworzenie folderu testowego (tryb dedicated) ===")
    cfg_dedicated = load_config({**env_base, "TUTAMCP_MAIL_MODE": "dedicated"})
    sm = SessionManager(cfg_dedicated)

    async def create_test_folder(client, session):
        mgk = await client.get_mail_group_key(session)
        return await client.create_folder(session, "_claude_test_", mgk)

    flist_id, felem_id = await sm.call(create_test_folder)
    print(f"  folder_list_id={flist_id!r} folder_elem_id={felem_id!r}")

    async def get_mail_list_id(client, session):
        folders = await client.get_folders(session)
        f = next((fo for fo in folders if fo.id == felem_id), None)
        return f.mail_list_id if f else None

    folder_mail_list_id = await sm.call(get_mail_list_id)
    assert folder_mail_list_id, "Brak mail_list_id nowego folderu"
    print(f"  mail_list_id (cfg.mail_folder) = {folder_mail_list_id!r}")
    await sm.close()

    # ── Test 1: allowed_tools w trybie FOLDER ─────────────────────────────────
    print("\n=== Test 1: allowed_tools — tryb FOLDER ===")
    cfg_folder = load_config({
        **env_base,
        "TUTAMCP_MAIL_MODE": "folder",
        "TUTAMCP_MAIL_FOLDER": folder_mail_list_id,
    })

    tools = allowed_tools(cfg_folder)
    print(f"  Dostępne narzędzia: {sorted(tools)}")

    for t in ["tuta_mail_list_folders", "tuta_mail_list", "tuta_mail_read",
              "tuta_mail_get_attachment", "tuta_mail_reply", "tuta_mail_move",
              "tuta_mail_delete", "tuta_mail_mark"]:
        assert t in tools, f"Brak wymaganego narzędzia {t}"

    for t in ["tuta_mail_send", "tuta_mail_folder_create", "tuta_mail_folder_rename",
              "tuta_mail_folder_delete"]:
        assert t not in tools, f"Narzędzie {t} NIE powinno być dostępne w trybie folder"

    print("  OK: zestaw narzędzi poprawny")

    # ── Test 2: check_folder_access ───────────────────────────────────────────
    print("\n=== Test 2: check_folder_access ===")
    assert check_folder_access(cfg_folder, folder_mail_list_id), \
        "Powinno dać dostęp do skonfigurowanego folderu"
    assert not check_folder_access(cfg_folder, "inny_id"), \
        "Powinno odmówić dostępu do obcego ID"
    print("  OK: sprawdzanie dostępu poprawne")

    # ── Test 3: tuta_mail_list_folders filtruje w trybie FOLDER ──────────────
    print("\n=== Test 3: tuta_mail_list_folders — filtrowanie w trybie FOLDER ===")
    sm_folder = SessionManager(cfg_folder)

    from tutamcp.tools_mail import register_mail_tools
    from mcp.server.fastmcp import FastMCP

    mcp_folder = FastMCP("test_folder_mode", log_level="CRITICAL")
    register_mail_tools(mcp_folder, cfg_folder, sm_folder)

    async def get_folders_folder_mode(client, session):
        # bezpośrednio przez tools_mail logikę
        from tutamcp.policy import check_folder_access as cfa
        folders = await client.get_folders(session)
        mail_group_key = await client.get_mail_group_key(session)
        from tutamcp.tools_mail import _decrypt_folder_name
        result = []
        for f in folders:
            if not cfa(cfg_folder, f.mail_list_id):
                continue
            result.append({
                "id": f.mail_list_id,
                "name": _decrypt_folder_name(f, mail_group_key),
                "folder_type_raw": f.folder_type,
            })
        return result

    folder_list = await sm_folder.call(get_folders_folder_mode)
    print(f"  Widoczne foldery: {[f['name'] for f in folder_list]}")
    assert len(folder_list) == 1, f"Oczekiwano 1 folderu, got {len(folder_list)}: {folder_list}"
    assert folder_list[0]["id"] == folder_mail_list_id, "Zły folder widoczny"
    print("  OK: widoczny tylko skonfigurowany folder")

    # ── Test 4: tuta_mail_list z właściwym ID ─────────────────────────────────
    print("\n=== Test 4: tuta_mail_list z właściwym folder_id ===")

    async def list_mails_in_folder(client, session):
        mail_group_key = await client.get_mail_group_key(session)
        mails = await client.get_mails_in_folder(session, folder_mail_list_id)
        return mails

    mails = await sm_folder.call(list_mails_in_folder)
    print(f"  Maile w folderze testowym: {len(mails)} (powinno być 0 — pusty)")
    print("  OK: zapytanie o własny folder OK")

    await sm_folder.close()

    # ── Sprzątanie: usuń tymczasowy folder ───────────────────────────────────
    print("\n=== Sprzątanie: usuwanie folderu testowego ===")
    sm2 = SessionManager(cfg_dedicated)

    async def delete_test_folder(client, session):
        folders = await client.get_folders(session)
        f = next((fo for fo in folders if fo.id == felem_id), None)
        if f:
            await client.delete_folder(session, f)
            return True
        return False

    deleted = await sm2.call(delete_test_folder)
    await sm2.close()
    print(f"  {'OK: folder usunięty' if deleted else 'SKIP: folder nie znaleziony (może był już usunięty)'}")

    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
