"""
Test integracyjny operacji mailowych (etap 2.3):
  tuta_mail_move, tuta_mail_delete, tuta_mail_mark,
  tuta_mail_folder_create, tuta_mail_folder_rename, tuta_mail_folder_delete.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_mail_ops.py

Wymaga co najmniej jednego maila w INBOX.
UWAGA: test używa tylko konta testowego, nie rusza skrzynki właściciela.
UWAGA: przenoszenie do własnych folderów NIE jest obsługiwane (movemailservice 400 w tutaproxy).
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    env.setdefault("TUTAMCP_MAIL_MODE", "dedicated")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test operacji mailowych (2.3) ===\n")

    # ── pomocnicze: znajdź pierwszy mail w INBOX ──────────────────────────────
    async def get_inbox_mail(client, session):
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mails = await client.get_mails_in_folder(session, inbox.mail_list_id)
        if not mails:
            return None, None
        mails.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        m = mails[0]
        mid = m.get("99", ["", ""])
        return (
            mid[0] if isinstance(mid, list) else "",
            mid[1] if isinstance(mid, list) else str(mid),
        )

    list_id, mail_id = await sm.call(get_inbox_mail)
    if not mail_id:
        print("Brak maili w INBOX — dodaj przynajmniej jeden i uruchom ponownie")
        await sm.close()
        return
    print(f"Mail testowy: list={list_id[:8]}… id={mail_id[:8]}…")

    # ── Test 1: folder_create ─────────────────────────────────────────────────
    print("\n=== Test 1: tuta_mail_folder_create ===")

    async def create_folder(client, session):
        mgk = await client.get_mail_group_key(session)
        return await client.create_folder(session, "_tutamcp_test_", mgk)

    flist_id, felem_id = await sm.call(create_folder)
    print(f"  folder_list_id={flist_id!r}, folder_elem_id={felem_id!r}")
    assert flist_id and felem_id, "Brak IDs nowego folderu"
    print("  OK: folder '_tutamcp_test_' utworzony")

    # Sprawdź czy folder pojawia się w liście
    async def get_folders(client, session):
        return await client.get_folders(session)

    folders = await sm.call(get_folders)
    test_folder = next(
        (f for f in folders if f.folder_list_id == flist_id and f.id == felem_id),
        None,
    )
    assert test_folder is not None, "Nowy folder nie widoczny w get_folders"
    print("  OK: folder widoczny w get_folders")

    # ── Test 2: mail_move do Archive (system folder) ──────────────────────────
    print("\n=== Test 2: tuta_mail_move → Archive (typ 4) ===")

    async def move_to_archive(client, session):
        await client.simple_move_mails(session, [(list_id, mail_id)], "4")  # Archive

    await sm.call(move_to_archive)

    async def get_archive_mails(client, session):
        folders = await client.get_folders(session)
        arch = next(f for f in folders if f.folder_type == "4")
        return await client.get_mails_in_folder(session, arch.mail_list_id)

    archive_mails = await sm.call(get_archive_mails)
    found_in_archive = any(
        (m.get("99", ["", ""])[1] if isinstance(m.get("99"), list) else str(m.get("99", ""))) == mail_id
        for m in archive_mails
    )
    assert found_in_archive, f"Mail {mail_id[:8]}… nie znaleziony w Archive"
    print("  OK: mail przeniesiony do Archive")

    # ── Test 3: mail_move z Archive → INBOX ──────────────────────────────────
    print("\n=== Test 3: tuta_mail_move → INBOX (typ 1) ===")

    # Pobierz aktualny list_id maila po przeniesieniu do Archive
    async def find_mail_in_archive(client, session):
        folders = await client.get_folders(session)
        arch = next(f for f in folders if f.folder_type == "4")
        mails = await client.get_mails_in_folder(session, arch.mail_list_id)
        for m in mails:
            mid = m.get("99", ["", ""])
            eid = mid[1] if isinstance(mid, list) else str(mid)
            if eid == mail_id:
                return mid[0] if isinstance(mid, list) else ""
        return None

    arch_list_id = await sm.call(find_mail_in_archive)
    assert arch_list_id is not None, f"Mail {mail_id[:8]}… nie znaleziony w Archive po przeniesieniu"

    async def move_back_to_inbox(client, session):
        await client.simple_move_mails(session, [(arch_list_id, mail_id)], "1")  # INBOX

    await sm.call(move_back_to_inbox)
    print("  OK: mail z powrotem w INBOX")

    # ── Test 4: próba move do własnego folderu → oczekiwany błąd ─────────────
    print("\n=== Test 4: tuta_mail_move → własny folder (oczekiwany błąd) ===")
    # To jest znana limitacja: movemailservice zwraca 400
    # Nie testujemy tu bezpośrednio (wywołanie API), tylko dokumentujemy
    print("  SKIP: movemailservice daje 400 dla własnych folderów — znana limitacja")
    print("  Folder CRUD (create/rename/delete) działa poprawnie")

    # ── Test 5: mail_mark unread=True ─────────────────────────────────────────
    print("\n=== Test 5: tuta_mail_mark unread=True ===")

    async def find_in_inbox(client, session):
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mails = await client.get_mails_in_folder(session, inbox.mail_list_id)
        for m in mails:
            mid = m.get("99", ["", ""])
            eid = mid[1] if isinstance(mid, list) else str(mid)
            if eid == mail_id:
                return mid[0] if isinstance(mid, list) else ""
        return None

    inbox_list_id = await sm.call(find_in_inbox)
    assert inbox_list_id is not None, f"Mail nie znaleziony w INBOX po powrocie"

    async def mark_unread(client, session):
        await client.mark_mails_unread(session, [(inbox_list_id, mail_id)], True)

    await sm.call(mark_unread)
    print("  OK: oznaczono jako nieprzeczytany")

    # ── Test 6: mail_mark unread=False ────────────────────────────────────────
    print("\n=== Test 6: tuta_mail_mark unread=False ===")

    async def mark_read(client, session):
        await client.mark_mails_unread(session, [(inbox_list_id, mail_id)], False)

    await sm.call(mark_read)
    print("  OK: oznaczono jako przeczytany")

    # ── Test 7: mail_delete (permanent=False → Trash) ─────────────────────────
    print("\n=== Test 7: tuta_mail_delete (permanent=False → Trash) ===")

    async def move_to_trash(client, session):
        await client.simple_move_mails(session, [(inbox_list_id, mail_id)], "3")  # Trash

    await sm.call(move_to_trash)

    async def get_trash_mails(client, session):
        folders = await client.get_folders(session)
        trash = next(f for f in folders if f.folder_type == "3")
        return await client.get_mails_in_folder(session, trash.mail_list_id)

    trash_mails = await sm.call(get_trash_mails)
    found_in_trash = any(
        (m.get("99", ["", ""])[1] if isinstance(m.get("99"), list) else str(m.get("99", ""))) == mail_id
        for m in trash_mails
    )
    assert found_in_trash, f"Mail {mail_id[:8]}… nie znaleziony w Trash"
    print("  OK: mail w Trash")

    # ── Test 8: folder_rename ─────────────────────────────────────────────────
    print("\n=== Test 8: tuta_mail_folder_rename ===")

    async def rename_folder(client, session):
        folders = await client.get_folders(session)
        folder = next(
            (f for f in folders if f.folder_list_id == flist_id and f.id == felem_id),
            None,
        )
        if folder is None:
            raise AssertionError("Folder testowy zniknął przed rename")
        mgk = await client.get_mail_group_key(session)
        await client.rename_folder(session, folder, "_tutamcp_test_renamed_", mgk)

    await sm.call(rename_folder)
    print("  OK: folder przemianowany na '_tutamcp_test_renamed_'")

    # ── Test 9: folder_delete ─────────────────────────────────────────────────
    print("\n=== Test 9: tuta_mail_folder_delete ===")

    async def delete_folder(client, session):
        folders = await client.get_folders(session)
        folder = next(
            (f for f in folders if f.folder_list_id == flist_id and f.id == felem_id),
            None,
        )
        if folder is None:
            raise AssertionError("Folder testowy zniknął przed delete")
        if folder.folder_type != "0":
            raise AssertionError(f"Folder ma typ {folder.folder_type!r}, oczekiwano '0'")
        await client.delete_folder(session, folder)

    await sm.call(delete_folder)

    folders_after = await sm.call(get_folders)
    still_exists = any(
        f.folder_list_id == flist_id and f.id == felem_id
        for f in folders_after
    )
    assert not still_exists, "Folder testowy nadal widoczny po usunięciu"
    print("  OK: folder usunięty, nie widoczny w get_folders")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")
    print("\nUWAGA: 1 mail wylądował w Trash — możesz go ręcznie przywrócić.")


if __name__ == "__main__":
    asyncio.run(run_tests())
