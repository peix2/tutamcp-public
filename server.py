"""
Entry point serwera MCP tutamcp.

Uruchamianie (przez run.py, który koryguje sys.path):
    /usr/bin/python3.11 run.py server.py

WAŻNE: stdout jest kanałem protokołu MCP (stdio transport). Żadne logi
ani print() nie mogą trafić na stdout — wyłącznie stderr lub plik.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

# --- sys.path (gdy server.py uruchamiany bezpośrednio przez run.py) ----------
_REPO = os.path.dirname(os.path.abspath(__file__))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import Config, ConfigError, MailMode, load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import register_mail_tools
from tutamcp.tools_calendar import register_calendar_tools
from tutamcp.tools_contacts import register_contacts_tools
from tutamcp.tools_drive import register_drive_tools

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _e:
    print(
        f"BŁĄD: pakiet mcp niedostępny ({_e}). "
        "Sprawdź .venv/lib/python3.11/site-packages.",
        file=sys.stderr,
    )
    sys.exit(1)

VERSION = "0.1.2"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(log_level: str, log_file: str | None) -> None:
    """Kieruje logi na stderr lub do pliku — nigdy na stdout."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))
    root.handlers.clear()

    if log_file:
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=50 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Budowanie serwera FastMCP
# ---------------------------------------------------------------------------

def build_server(cfg: Config, sm: SessionManager) -> FastMCP:
    """Tworzy i zwraca FastMCP z zarejestrowanymi narzędziami."""

    @asynccontextmanager
    async def lifespan(_mcp: FastMCP):
        logger.info("tutamcp %s — start", VERSION)
        try:
            yield {}
        finally:
            logger.info("tutamcp — shutdown, wylogowuję sesję")
            await sm.close()

    # log_level="WARNING" → FastMCP nie drukuje własnych info-logów na stderr
    # (mamy własny handler; żeby uniknąć duplikatów ustawiamy CRITICAL)
    mcp = FastMCP("tutamcp", lifespan=lifespan, log_level="CRITICAL")

    # --- narzędzia warunkowe (na razie tylko tuta_status, bezwarunkowo) -----

    @mcp.tool()
    def tuta_status() -> dict[str, Any]:
        """
        Returns tutamcp server status.

        Reports: version, list of enabled modules, mail settings, and session state
        (whether the server is logged in and with which account). Does NOT trigger
        a login — use any other tool to initiate a session.
        """
        modules = []
        if cfg.enable_mail:
            modules.append("mail")
        if cfg.enable_calendar:
            modules.append("calendar")
        if cfg.enable_contacts:
            modules.append("contacts")
        if cfg.enable_drive:
            modules.append("drive")

        logged_in = sm._session is not None
        account = sm._session.user_email if sm._session else None

        return {
            "version": VERSION,
            "modules": modules,
            "mail_mode": cfg.mail_mode.value if cfg.enable_mail else None,
            "mail_send": cfg.mail_send.value if cfg.enable_mail else None,
            "session": {
                "logged_in": logged_in,
                "account": account,
            },
        }

    # --- warunkowa rejestracja narzędzi modułów ---
    if cfg.enable_mail:
        register_mail_tools(mcp, cfg, sm)
    if cfg.enable_calendar:
        register_calendar_tools(mcp, cfg, sm)
    if cfg.enable_contacts:
        register_contacts_tools(mcp, cfg, sm)
    if cfg.enable_drive:
        register_drive_tools(mcp, cfg, sm)

    return mcp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"BŁĄD konfiguracji tutamcp: {e}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(cfg.log_level, cfg.log_file)
    logger.info("tutamcp %s — konfiguracja wczytana, moduły: mail=%s cal=%s cont=%s drive=%s",
                VERSION, cfg.enable_mail, cfg.enable_calendar, cfg.enable_contacts, cfg.enable_drive)

    sm = SessionManager(cfg)
    mcp = build_server(cfg, sm)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
