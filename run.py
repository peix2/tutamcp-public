#!/usr/bin/env python3
"""
Uruchamia dowolny skrypt z poprawnym sys.path.
Użycie: /usr/bin/python3.11 run.py <skrypt.py> [args...]

Powód (jak w tutaproxy): venv symlink wskazuje na /home/node/.python
(broken — /home jest noexec). Pakiety są w .venv/lib/python3.11/site-packages;
używamy systemowego python3.11.

Kolejność ścieżek (ważne):
1. katalog repo (pakiet tutamcp)
2. lokalny .venv (mcp SDK i zależności)
3. repo tutaproxy (pakiet tuta — klient API)
4. .venv tutaproxy (aiohttp, argon2, kyber, lz4...)
Dzięki temu cryptography bierze się z tutaproxy (44.0.3, przetestowana
z tuta.crypto), a mcp ze swojego venva.
"""
import sys
import os

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
TUTAPROXY_PATH = os.environ.get("TUTAPROXY_PATH", "")

sys.path = [p for p in sys.path if not p.startswith("/home")]
sys.path.insert(0, os.path.join(TUTAPROXY_PATH, ".venv/lib/python3.11/site-packages"))
sys.path.insert(0, TUTAPROXY_PATH)
sys.path.insert(0, os.path.join(REPO_DIR, ".venv/lib/python3.11/site-packages"))
sys.path.insert(0, REPO_DIR)

if len(sys.argv) > 1:
    script = sys.argv.pop(1)
    with open(script) as f:
        exec(compile(f.read(), script, "exec"), {"__name__": "__main__", "__file__": script})
