"""
Test integracyjny tuta_mail_read.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_mail_read.py

Wymaga maili w INBOX (co najmniej jednego tekstowego i jednego HTML).
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import _read_mail_full


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    # pobierz listę maili z INBOX
    async def get_inbox_mails(client, session):
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mail_group_key = await client.get_mail_group_key(session)
        mails_raw = await client.get_mails_in_folder(session, inbox.mail_list_id)
        mails_raw.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        return mails_raw[:10], mail_group_key, inbox.mail_list_id

    mails_raw, mail_group_key, inbox_list_id = await sm.call(get_inbox_mails)
    assert mails_raw, "Brak maili w INBOX — dodaj kilka z UI Tuty"

    print(f"Maile w INBOX: {len(mails_raw)}, testuję pierwsze {min(3, len(mails_raw))}\n")

    for i, mail_raw in enumerate(mails_raw[:3]):
        mid = mail_raw.get("99", ["", ""])
        list_id = mid[0] if isinstance(mid, list) else inbox_list_id
        elem_id = mid[1] if isinstance(mid, list) else str(mid)
        has_attach = bool(mail_raw.get("115"))

        print(f"=== Mail {i+1}: {elem_id[:8]}... (załączniki: {has_attach}) ===")

        async def read_one(client, session, li=list_id, ei=elem_id):
            mgk = await client.get_mail_group_key(session)
            return await _read_mail_full(client, session, mgk, li, ei)

        result = await sm.call(read_one)

        print(f"  Subject : {result.get('subject')}")
        print(f"  From    : {result.get('from')}")
        print(f"  To      : {result.get('to')}")
        print(f"  CC      : {result.get('cc')}")
        print(f"  Date    : {result.get('date')}")
        print(f"  Unread  : {result.get('unread')}")
        print(f"  Attachm.: {result.get('attachments')}")
        body = result.get("body", "")
        body_preview = body[:200].replace("\n", "↵") if body else ""
        print(f"  Body    : {body_preview!r}")
        if result.get("body_truncated"):
            print(f"  [TRUNCATED — body > 50 KB]")
        if "error" in result:
            print(f"  ERROR: {result['error']}")

        # asercje
        assert "subject" in result, "Brak 'subject'"
        assert "from" in result, "Brak 'from'"
        assert "to" in result, "Brak 'to'"
        assert "date" in result, "Brak 'date'"
        assert "body" in result, "Brak 'body'"
        if not result.get("error"):
            assert result["subject"] != "(szyfrowanie niedostępne)", "Błąd deszyfrowania"
        print()

    await sm.close()
    print("=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
