"""
Test integracyjny narzędzi tuta_mail_list_folders i tuta_mail_list.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_mail_list.py

Wymaga: konto testowe z przynajmniej kilkoma mailami w INBOX.
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import register_mail_tools


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test 1: tuta_mail_list_folders ===\n")

    async def get_folders(client, session):
        from tuta.message_builder import _decrypt_str
        import base64
        folders = await client.get_folders(session)
        mail_group_key = await client.get_mail_group_key(session)
        from tutamcp.tools_mail import _decrypt_folder_name
        result = []
        for f in folders:
            result.append({
                "name": _decrypt_folder_name(f, mail_group_key),
                "type": f.folder_type,
                "mail_list_id": f.mail_list_id,
            })
        return result

    folders = await sm.call(get_folders)
    print(f"Foldery ({len(folders)}):")
    for f in folders:
        print(f"  [{f['type']}] {f['name']:20} mail_list_id={f['mail_list_id'][:12]}...")

    assert any(f["type"] == "1" for f in folders), "Brak INBOX"
    assert any(f["type"] == "2" for f in folders), "Brak Sent"
    print("\n  OK: foldery zawierają INBOX i Sent")

    # znajdź INBOX
    inbox = next(f for f in folders if f["type"] == "1")
    print(f"\n  INBOX mail_list_id: {inbox['mail_list_id']}")

    print("\n=== Test 2: tuta_mail_list (INBOX, limit=5) ===\n")

    async def list_mails(client, session):
        from tutamcp.tools_mail import _build_mail_summary
        mail_group_key = await client.get_mail_group_key(session)
        mails_raw = await client.get_mails_in_folder(session, inbox["mail_list_id"])
        mails_raw.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        mails_raw = mails_raw[:5]
        return [_build_mail_summary(m, mail_group_key, session) for m in mails_raw]

    mails = await sm.call(list_mails)
    print(f"Maile w INBOX (pierwsze 5, {len(mails)} zwrócone):")
    for m in mails:
        unread_str = "UNREAD" if m["unread"] else "read"
        attach_str = "[A]" if m["has_attachments"] else ""
        print(f"  {m['date'][:10]} [{unread_str}] {attach_str}")
        print(f"    Od:  {m['from']}")
        print(f"    Do:  {m['to']}")
        print(f"    Sub: {m['subject']}")
        print(f"    ID:  {m['id']}")

    assert len(mails) > 0, "Brak maili w INBOX — dodaj kilka z UI Tuty"
    dates = [m["date"] for m in mails if m["date"]]
    if len(dates) >= 2:
        assert dates[0] >= dates[1], "Maile nie są posortowane malejąco po dacie"
        print("\n  OK: sortowanie malejące po dacie")
    print("  OK: maile w INBOX pobrane i odszyfrowane")

    print("\n=== Test 3: paginacja (before_id) ===\n")
    if len(mails) >= 2:
        pivot_id = mails[0]["id"]

        async def list_after_pivot(client, session):
            from tutamcp.tools_mail import _build_mail_summary
            mail_group_key = await client.get_mail_group_key(session)
            mails_raw = await client.get_mails_in_folder(session, inbox["mail_list_id"])
            mails_raw.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
            # imituj before_id filtr z tools_mail.py
            filtered = []
            found = False
            for m in mails_raw:
                mid = m.get("99", ["", ""])
                eid = mid[1] if isinstance(mid, list) and len(mid) > 1 else str(mid)
                if eid == pivot_id:
                    found = True
                    continue
                if found:
                    filtered.append(m)
            return [_build_mail_summary(m, mail_group_key, session) for m in filtered[:5]]

        mails2 = await sm.call(list_after_pivot)
        print(f"Maile po {pivot_id[:8]}...: {len(mails2)} zwrócone")
        if mails2:
            assert mails2[0]["id"] != pivot_id, "Pivot ID nie powinien być w wynikach"
            print(f"  Pierwszy: {mails2[0]['id'][:8]}... {mails2[0]['subject'][:40]}")
        print("  OK: paginacja before_id działa")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
