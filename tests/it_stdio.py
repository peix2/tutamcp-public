"""
Test integracyjny server.py przez stdio transport — bez Claude'a, bez sieci.

Odpala serwer jako subproces, woła list_tools i tuta_status, sprawdza odpowiedzi.
Uruchamianie: /usr/bin/python3.11 run.py tests/it_stdio.py
"""

import asyncio
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
except ImportError as e:
    print(f"BŁĄD importu mcp SDK: {e}")
    sys.exit(1)

TUTAPROXY_PATH = os.environ.get("TUTAPROXY_PATH", "")
PYTHON = "/usr/bin/python3.11"
RUN_PY = os.path.join(_REPO, "run.py")
SERVER_PY = os.path.join(_REPO, "server.py")


async def run_tests() -> None:
    # serwer startuje bez włączonych modułów → nie wymaga danych logowania
    server_env = {
        "TUTAPROXY_PATH": TUTAPROXY_PATH,
        "TUTAMCP_ENABLE_MAIL": "0",
        "TUTAMCP_ENABLE_CALENDAR": "0",
        "TUTAMCP_ENABLE_CONTACTS": "0",
        "TUTAMCP_ENABLE_DRIVE": "0",
        "LOG_LEVEL": "WARNING",
    }

    params = StdioServerParameters(
        command=PYTHON,
        args=[RUN_PY, SERVER_PY],
        env=server_env,
    )

    print("Uruchamiam serwer tutamcp przez stdio...")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client_session:
            await client_session.initialize()
            print("  OK: połączono z serwerem")

            # --- list_tools ---
            print("\n[1] list_tools...")
            tools_result = await client_session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"    Narzędzia: {tool_names}")
            assert "tuta_status" in tool_names, f"Brak tuta_status w liście narzędzi: {tool_names}"
            print("    OK: tuta_status widoczne")

            # --- tuta_status ---
            print("\n[2] tuta_status...")
            result = await client_session.call_tool("tuta_status", {})
            assert result.content, "Puste content w odpowiedzi tuta_status"
            raw_text = result.content[0].text
            print(f"    Odpowiedź surowa: {raw_text!r}")

            data = json.loads(raw_text)
            print(f"    Wersja: {data.get('version')}")
            print(f"    Moduły: {data.get('modules')}")
            print(f"    Sesja: {data.get('session')}")

            assert "version" in data, "Brak 'version' w odpowiedzi"
            assert "modules" in data, "Brak 'modules' w odpowiedzi"
            assert "session" in data, "Brak 'session' w odpowiedzi"
            assert data["modules"] == [], f"Oczekiwano pustej listy modułów, got: {data['modules']}"
            assert data["session"]["logged_in"] is False, "Nie powinno być aktywnej sesji"
            assert data["session"]["account"] is None, "Konto powinno być None"
            print("    OK: status poprawny")

            # --- tuta_status z włączoną pocztą (osobna instancja serwera) ---
            print("\n[3] tuta_status z włączoną pocztą (dedykowany, domyślny)...")

    # nowa sesja z włączoną pocztą
    server_env_mail = dict(server_env)
    server_env_mail.update({
        "TUTAMCP_ENABLE_MAIL": "1",
        "TUTA_EMAIL": "test@example.com",
        "TUTA_PASSWORD": "placeholder_not_used_by_status",
    })
    params_mail = StdioServerParameters(
        command=PYTHON,
        args=[RUN_PY, SERVER_PY],
        env=server_env_mail,
    )

    async with stdio_client(params_mail) as (read2, write2):
        async with ClientSession(read2, write2) as cs2:
            await cs2.initialize()
            result2 = await cs2.call_tool("tuta_status", {})
            data2 = json.loads(result2.content[0].text)
            print(f"    Odpowiedź: {data2}")
            assert "mail" in data2["modules"], f"Brak 'mail' w modułach: {data2['modules']}"
            assert data2["mail_mode"] == "dedicated", f"Oczekiwano dedicated, got: {data2['mail_mode']}"
            assert data2["mail_send"] == "full", f"Oczekiwano full (default dla dedicated), got: {data2['mail_send']}"
            assert data2["session"]["logged_in"] is False, "tuta_status nie powinien logować"
            print("    OK: mail_mode=dedicated, mail_send=full, sesja nieaktywna")

    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
