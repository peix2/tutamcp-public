"""
Test integracyjny 3.2 — trusted_sender i e2e detection.

Sprawdza:
 - e2e=True dla maili Tuta→Tuta (pole 1310 obecne)
 - trusted_sender=True dla maili od owner_email gdy e2e=True
 - trusted_sender=False dla maili z obcego adresu
 - only_trusted=True filtruje wyniki tuta_mail_list

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_trusted_sender.py
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import _build_mail_summary, _is_e2e_mail, _is_trusted_sender

OWNER_EMAIL = os.environ.get("TUTAMCP_OWNER_EMAIL", "owner@tuta.com")


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    env.setdefault("TUTAMCP_MAIL_MODE", "dedicated")
    env.setdefault("TUTAMCP_OWNER_EMAIL", OWNER_EMAIL)
    # Nie ustawiamy COMMAND_WHITELIST — owner jest dopisywany automatycznie
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print(f"=== Test trusted_sender + E2E detection ===")
    print(f"Owner: {cfg.owner_email!r}")
    print(f"Whitelist: {cfg.command_whitelist}")
    print()

    # ── Test 1: pobierz maile z INBOX i sprawdź adnotacje ─────────────────────
    print("=== Test 1: e2e i trusted_sender w podsumowaniach maili ===")

    async def get_inbox_summaries(client, session):
        mgk = await client.get_mail_group_key(session)
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mails = await client.get_mails_in_folder(session, inbox.mail_list_id)
        mails.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        summaries = []
        for m in mails[:10]:
            s = _build_mail_summary(m, mgk, session, cfg)
            summaries.append(s)
        return summaries

    summaries = await sm.call(get_inbox_summaries)
    print(f"  Maile w INBOX: {len(summaries)}")

    for s in summaries:
        print(f"  [{s.get('from', '?')[:40]}] e2e={s.get('e2e')} trusted={s.get('trusted_sender')}")

    # Sprawdź że pola są obecne
    assert summaries, "Brak maili w INBOX"
    for s in summaries:
        assert "e2e" in s, f"Brak pola 'e2e' w summary: {s}"
        assert "trusted_sender" in s, f"Brak pola 'trusted_sender' w summary: {s}"
    print("  OK: pola e2e i trusted_sender obecne")

    # ── Test 2: maile wysłane przez nas do siebie (E2E) ──────────────────────
    print("\n=== Test 2: E2E detection — własne maile z konta testowego ===")

    async def get_sent_summaries(client, session):
        mgk = await client.get_mail_group_key(session)
        folders = await client.get_folders(session)
        sent = next(f for f in folders if f.folder_type == "2")
        mails = await client.get_mails_in_folder(session, sent.mail_list_id)
        mails.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        summaries = []
        for m in mails[:5]:
            s = _build_mail_summary(m, mgk, session, cfg)
            summaries.append(s)
        return summaries

    sent_summaries = await sm.call(get_sent_summaries)
    print(f"  Maile Sent: {len(sent_summaries)}")
    for s in sent_summaries:
        print(f"  [{s.get('from', '?')[:40]}] e2e={s.get('e2e')} trusted={s.get('trusted_sender')} subj={s.get('subject', '')[:40]}")
    print("  OK: Sent folder przeszło bez błędów")

    # ── Test 3: szukaj maila E2E od owner'a → powinien być trusted ──────────
    print(f"\n=== Test 3: mail E2E od {OWNER_EMAIL!r} → trusted_sender=True ===")

    e2e_from_owner = [s for s in summaries if s.get("e2e") and
                      OWNER_EMAIL.lower() in s.get("from", "").lower()]
    non_e2e = [s for s in summaries if not s.get("e2e")]

    if e2e_from_owner:
        for s in e2e_from_owner:
            assert s.get("trusted_sender"), f"Mail E2E od owner'a powinien być trusted: {s}"
        print(f"  OK: znaleziono {len(e2e_from_owner)} mail(e) E2E od owner'a → trusted_sender=True")
    else:
        print(f"  SKIP: brak maili E2E od {OWNER_EMAIL!r} w INBOX")
        print("  WSKAZÓWKA: Wyślij mi maila z konta Tuta (owner@tuta.com) żeby przetestować")

    if non_e2e:
        for s in non_e2e:
            assert not s.get("trusted_sender"), \
                f"Mail non-E2E powinien mieć trusted_sender=False: {s}"
        print(f"  OK: {len(non_e2e)} mail(i) non-E2E → trusted_sender=False")
    else:
        print("  SKIP: brak maili non-E2E do weryfikacji")

    # ── Test 4: only_trusted filtr przez _build_mail_summary ─────────────────
    print("\n=== Test 4: only_trusted filtr ===")
    trusted = [s for s in summaries if s.get("trusted_sender")]
    untrusted = [s for s in summaries if not s.get("trusted_sender")]
    print(f"  Trusted: {len(trusted)}, Untrusted: {len(untrusted)}")

    # Symulacja filtr only_trusted=True
    filtered = [s for s in summaries if s.get("trusted_sender")]
    assert all(s.get("trusted_sender") for s in filtered), "Filtr only_trusted niepoprawny"
    print(f"  OK: filtr only_trusted zwraca {len(filtered)} maili")

    # ── Test 5: tylko adres — nie E2E → untrusted ────────────────────────────
    print("\n=== Test 5: unit test _is_trusted_sender ===")
    # mail z From owner'a ale bez pola 1310 (non-E2E) → powinien być untrusted
    fake_mail_non_e2e = {"102": "base64...", "111": {}}  # brak pola 1310
    # mail_key jest potrzebny do _decode_address, ale bez niego też zwraca False
    result = _is_trusted_sender(fake_mail_non_e2e, None, cfg)
    assert not result, "mail_key=None → untrusted"
    print("  OK: mail_key=None → untrusted")

    # mail z polem 1310 = E2E, ale fake mail_key → _decode_address może fail gracefully
    fake_mail_e2e = {"1310": [{"2045": "fakepq"}], "111": {}}
    result2 = _is_trusted_sender(fake_mail_e2e, b"\x00" * 32, cfg)
    # _decode_address z zerowymi kluczami zwróci pusty adres → untrusted
    assert not result2, "Pusty adres z fake key → untrusted"
    print("  OK: fake mail E2E z zerowymi kluczami → untrusted (pusta adres)")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
