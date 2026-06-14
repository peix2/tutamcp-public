"""
Test integracyjny SessionManager — wymaga połączenia z API Tuty i prawdziwego konta.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_session.py

Albo przez plik credentials:
    TUTAMCP_CREDENTIALS_FILE=/ścieżka/creds.env /usr/bin/python3.11 run.py tests/it_session.py

Test: login (lazy) → get_folders → symulacja 440 (podmiana tokenu) → auto re-login → logout.
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config, ConfigError
from tutamcp.session import SessionManager


async def run_tests() -> None:
    # --- ładowanie konfiguracji ---
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    try:
        cfg = load_config(env)
    except ConfigError as e:
        print(f"BŁĄD konfiguracji: {e}")
        sys.exit(1)

    print(f"Konto: {cfg.email}")
    sm = SessionManager(cfg)

    # --- 1. lazy login: pierwsze get() loguje ---
    print("\n[1] Lazy login — pierwsze get()...")
    client, session = await sm.get()
    assert session.user_email, "session.user_email puste po logowaniu"
    print(f"    OK: zalogowano jako {session.user_email}")

    # --- 2. get_folders — weryfikacja działającej sesji ---
    print("\n[2] get_folders przez call()...")
    # folder_type: "1"=INBOX, "2"=SENT, "3"=TRASH, "4"=ARCHIVE, "5"=SPAM, "6"=DRAFT, "0"=własny
    folders = await sm.call(lambda c, s: c.get_folders(s))
    type_map = {"1": "INBOX", "2": "SENT", "3": "TRASH", "4": "ARCHIVE", "5": "SPAM", "6": "DRAFT"}
    folder_desc = [type_map.get(f.folder_type, f"custom:{f.folder_type}") for f in folders]
    print(f"    OK: {len(folders)} folderów: {folder_desc[:5]}")
    assert any(f.folder_type == "1" for f in folders), "Brak folderu INBOX w liście folderów"

    # --- 3. symulacja wygaśnięcia sesji: podmiana tokenu ---
    print("\n[3] Symulacja 440 — podmiana access_token na 'broken_token'...")
    original_token = sm._session.access_token
    sm._session.access_token = "broken_token_for_testing"
    print(f"    Token zmieniony: {original_token[:8]}... → broken_token_for_testing")

    # --- 4. wywołanie, które powinno wywołać 440 → re-login → sukces ---
    print("\n[4] get_folders po 'wygaśnięciu' — oczekiwany auto re-login...")
    folders2 = await sm.call(lambda c, s: c.get_folders(s))
    print(f"    OK: {len(folders2)} folderów po re-logowaniu")
    assert len(folders2) > 0, "Brak folderów po re-logowaniu"

    # upewnij się, że sesja jest naprawdę nowa
    client2, session2 = await sm.get()
    assert session2.access_token != "broken_token_for_testing", (
        "Token powinien być odświeżony po re-logowaniu"
    )
    print(f"    Nowy token: {session2.access_token[:8]}...")

    # --- 5. graceful logout ---
    print("\n[5] Graceful logout (close)...")
    await sm.close()
    assert sm._client is None, "_client powinien być None po close()"
    assert sm._session is None, "_session powinien być None po close()"
    print("    OK: wylogowano, _client i _session wyczyszczone")

    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
