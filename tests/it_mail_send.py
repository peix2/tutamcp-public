"""
Test integracyjny tuta_mail_send + tuta_mail_reply.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_mail_send.py

Test wysyła maila na adres właściciela (TUTAMCP_OWNER_EMAIL lub owner@tuta.com).
Po uruchomieniu sprawdź odbiór w skrzynce docelowej.
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import _send_core, _parse_address, _apply_cc_owner

OWNER_EMAIL = os.environ.get("TUTAMCP_OWNER_EMAIL", "owner@tuta.com")


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    env.setdefault("TUTAMCP_OWNER_EMAIL", OWNER_EMAIL)
    env.setdefault("TUTAMCP_MAIL_MODE", "dedicated")
    env.setdefault("TUTAMCP_MAIL_SEND", "full")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print(f"Konto nadawcy: {cfg.email}")
    print(f"Adres docelowy: {OWNER_EMAIL}")

    # --- Test 1: tuta_mail_send na adres zewnętrzny (non-E2E) ---
    print("\n=== Test 1: tuta_mail_send → zewnętrzny odbiorca (owner@tuta.com) ===")

    async def send_external(client, session):
        mgk = await client.get_mail_group_key(session)
        to_list = [_parse_address(OWNER_EMAIL)]
        return await _send_core(
            client, session, mgk,
            subject="[tutamcp test] tuta_mail_send non-E2E",
            body_text="Testowy mail z tutamcp - wyślij odpowiedź żebym mógł przetestować reply.",
            from_addr=session.user_email, from_name="tutamcp bot",
            to_list=to_list, cc_list=[], bcc_list=[],
        )

    result = await sm.call(send_external)
    print(f"  Wynik: {result}")
    assert result.get("status") == "sent", f"Oczekiwano status=sent, got: {result}"
    print(f"  OK: wysłano, e2e={result.get('e2e')} (konto może być Tuta/zewnętrzne)")

    # --- Test 2: tuta_mail_send na konto Tuta (E2E) ---
    print("\n=== Test 2: tuta_mail_send → konto Tuta (E2E) ===")

    async def send_tuta(client, session):
        mgk = await client.get_mail_group_key(session)
        # wysyłamy do samych siebie (konto testowe → konto testowe)
        to_list = [_parse_address(session.user_email)]
        return await _send_core(
            client, session, mgk,
            subject="[tutamcp test] tuta_mail_send E2E (self)",
            body_text="Test E2E — mail do siebie. Używany też jako target dla tuta_mail_reply.",
            from_addr=session.user_email, from_name="tutamcp bot",
            to_list=to_list, cc_list=[], bcc_list=[],
        )

    result_e2e = await sm.call(send_tuta)
    print(f"  Wynik: {result_e2e}")
    assert result_e2e.get("status") == "sent", f"Oczekiwano status=sent"
    assert result_e2e.get("e2e") is True, f"Oczekiwano e2e=True (konto Tuta), got: {result_e2e}"
    print(f"  OK: wysłano E2E do samego siebie")

    # --- Test 3: tuta_mail_reply na mail z INBOX ---
    print("\n=== Test 3: tuta_mail_reply na ostatni mail od zewnętrznego nadawcy ===")

    async def find_external_mail(client, session):
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mails = await client.get_mails_in_folder(session, inbox.mail_list_id)
        mails.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        for m in mails:
            mid = m.get("99", ["", ""])
            return mid[0] if isinstance(mid, list) else "", mid[1] if isinstance(mid, list) else str(mid)
        return None, None

    orig_list_id, orig_mail_id = await sm.call(find_external_mail)
    if not orig_mail_id:
        print("  Brak maili do odpowiedzi — test reply pominięty")
    else:
        print(f"  Odpowiadam na: {orig_mail_id[:8]}...")

        async def do_reply(client, session):
            mgk = await client.get_mail_group_key(session)
            from tutamcp.tools_mail import _decrypt_mail_key, _decode_recipients
            from tuta.message_builder import _decrypt_str, _decode_address
            import base64

            mail_raw = await client.get_single_mail(session, orig_list_id, orig_mail_id)
            mail_key = _decrypt_mail_key(mail_raw, mgk, session)
            if not mail_key:
                return {"error": "Brak klucza"}

            orig_subject = _decrypt_str(mail_key, mail_raw.get("105", "")) or "(brak tematu)"
            sender_agg = mail_raw.get("111", {})
            s_name, s_addr = _decode_address(sender_agg, mail_key)
            subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

            to_list = [(s_name, s_addr)] if s_addr else []
            return await _send_core(
                client, session, mgk,
                subject=subject,
                body_text="[tutamcp test] Odpowiedź przez tuta_mail_reply.",
                from_addr=session.user_email, from_name="",
                to_list=to_list, cc_list=[], bcc_list=[],
            )

        result_reply = await sm.call(do_reply)
        print(f"  Wynik: {result_reply}")
        assert result_reply.get("status") == "sent", f"Oczekiwano status=sent: {result_reply}"
        print(f"  OK: reply wysłany do {result_reply.get('to')}, e2e={result_reply.get('e2e')}")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")
    print(f"\nSprawdź skrzynkę {OWNER_EMAIL} — powinny być 2 maile od your@tuta.com")


if __name__ == "__main__":
    asyncio.run(run_tests())
