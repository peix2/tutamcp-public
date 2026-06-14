"""
Konfiguracja serwera tutamcp.

Kolejność ładowania:
1. zmienne środowiskowe
2. plik credentials (TUTAMCP_CREDENTIALS_FILE) — nadpisuje env dla TUTA_EMAIL/TUTA_PASSWORD

Błędy startu (ConfigError):
- TUTAMCP_CREDENTIALS_FILE ustawiony, ale plik nie istnieje
- tryb folder bez TUTAMCP_MAIL_FOLDER
- tryb folder z mail_send=full (jawnie w configu)
- email/password brakuje, gdy co najmniej jeden moduł włączony
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MailMode(Enum):
    DEDICATED = "dedicated"
    SHARED = "shared"
    FOLDER = "folder"


class MailSend(Enum):
    REPLY_ONLY = "reply_only"
    FULL = "full"


class ConfigError(Exception):
    """Błąd konfiguracji — nieprawidłowe lub brakujące wartości."""


@dataclass
class Config:
    enable_mail: bool
    enable_calendar: bool
    enable_contacts: bool
    enable_drive: bool

    mail_mode: MailMode
    mail_folder: Optional[str]
    mail_send: MailSend

    owner_email: str
    # owner zawsze należy do whitelisty; lista znormalizowana do lowercase
    command_whitelist: list[str]
    cc_owner: bool

    email: Optional[str]
    password: Optional[str]

    download_dir: str
    tutaproxy_path: str

    log_level: str
    log_file: Optional[str]

    # True (domyślnie): zaufanie wymaga E2E (pole 1310); False: tylko sprawdzamy adres
    trust_require_e2e: bool = True


def _parse_bool(val: str) -> bool:
    return val.strip() in ("1", "true", "yes", "True", "Yes")


def _load_credentials_file(path: str) -> dict[str, str]:
    """Wczytuje plik credentials w formacie KEY=VALUE (jak .env)."""
    if not os.path.exists(path):
        raise ConfigError(
            f"Plik credentials nie istnieje: {path!r}\n"
            "Sprawdź ścieżkę w TUTAMCP_CREDENTIALS_FILE."
        )
    # Sprawdź uprawnienia pliku — credentials powinny być tylko dla właściciela (0600)
    try:
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077:  # group lub other ma jakikolwiek dostęp
            import sys
            print(
                f"OSTRZEŻENIE BEZPIECZEŃSTWA: plik credentials {path!r} ma uprawnienia "
                f"{oct(mode)} — powinno być 0600 (chmod 600 {path})",
                file=sys.stderr,
            )
    except OSError:
        pass
    result: dict[str, str] = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                result[key] = val
    return result


def load_config(env: Optional[dict[str, str]] = None) -> Config:
    """
    Loads config from environment variables (or provided dict).
    Credentials file overrides TUTA_EMAIL/TUTA_PASSWORD if set.
    Raises ConfigError on invalid/missing configuration.
    """
    e = env if env is not None else os.environ

    # dane dostępowe: najpierw env, potem plik credentials
    email: Optional[str] = e.get("TUTA_EMAIL") or None
    password: Optional[str] = e.get("TUTA_PASSWORD") or None

    creds_file = e.get("TUTAMCP_CREDENTIALS_FILE", "").strip()
    if creds_file:
        creds = _load_credentials_file(creds_file)
        if "TUTA_EMAIL" in creds:
            email = creds["TUTA_EMAIL"]
        if "TUTA_PASSWORD" in creds:
            password = creds["TUTA_PASSWORD"]

    enable_mail = _parse_bool(e.get("TUTAMCP_ENABLE_MAIL", "0"))
    enable_calendar = _parse_bool(e.get("TUTAMCP_ENABLE_CALENDAR", "0"))
    enable_contacts = _parse_bool(e.get("TUTAMCP_ENABLE_CONTACTS", "0"))
    enable_drive = _parse_bool(e.get("TUTAMCP_ENABLE_DRIVE", "0"))

    any_module = enable_mail or enable_calendar or enable_contacts or enable_drive
    if any_module and not email:
        raise ConfigError(
            "Brakuje TUTA_EMAIL — wymagane gdy włączony jest co najmniej jeden moduł."
        )
    if any_module and not password:
        raise ConfigError(
            "Brakuje TUTA_PASSWORD — wymagane gdy włączony jest co najmniej jeden moduł."
        )

    # tryb konta
    raw_mode = e.get("TUTAMCP_MAIL_MODE", "dedicated").strip().lower()
    try:
        mail_mode = MailMode(raw_mode)
    except ValueError:
        raise ConfigError(
            f"Nieprawidłowy TUTAMCP_MAIL_MODE: {raw_mode!r}. "
            "Dozwolone wartości: dedicated, shared, folder."
        )

    mail_folder: Optional[str] = e.get("TUTAMCP_MAIL_FOLDER", "").strip() or None
    if mail_mode == MailMode.FOLDER and not mail_folder:
        raise ConfigError(
            "Tryb folder wymaga ustawionego TUTAMCP_MAIL_FOLDER."
        )

    # polityka wysyłki: domyślna zależy od trybu
    raw_send = e.get("TUTAMCP_MAIL_SEND", "").strip().lower()
    if raw_send:
        try:
            mail_send = MailSend(raw_send)
        except ValueError:
            raise ConfigError(
                f"Nieprawidłowy TUTAMCP_MAIL_SEND: {raw_send!r}. "
                "Dozwolone wartości: reply_only, full."
            )
        # tryb folder nie może mieć FULL
        if mail_mode == MailMode.FOLDER and mail_send == MailSend.FULL:
            raise ConfigError(
                "Tryb folder wymusza politykę reply_only. "
                "Jawne ustawienie TUTAMCP_MAIL_SEND=full jest niedozwolone."
            )
    else:
        # domyślna polityka zależna od trybu
        if mail_mode == MailMode.DEDICATED:
            mail_send = MailSend.FULL
        else:
            # shared i folder → reply_only
            mail_send = MailSend.REPLY_ONLY

    owner_email = e.get("TUTAMCP_OWNER_EMAIL", "").strip()

    # whitelista: CSV, normalizacja lowercase, owner zawsze dopisany
    raw_whitelist = e.get("TUTAMCP_COMMAND_WHITELIST", "").strip()
    whitelist: list[str] = (
        [addr.strip().lower() for addr in raw_whitelist.split(",") if addr.strip()]
        if raw_whitelist else []
    )
    if owner_email and owner_email.lower() not in whitelist:
        whitelist.append(owner_email.lower())

    cc_owner = _parse_bool(e.get("TUTAMCP_MAIL_CC_OWNER", "0"))
    trust_require_e2e = _parse_bool(e.get("TUTAMCP_TRUST_REQUIRE_E2E", "1"))

    download_dir = e.get("TUTAMCP_DOWNLOAD_DIR", "/tmp/tutamcp").strip()
    tutaproxy_path = e.get("TUTAPROXY_PATH", "").strip()
    log_level = e.get("LOG_LEVEL", "INFO").strip().upper()
    log_file: Optional[str] = e.get("LOG_FILE", "").strip() or None

    return Config(
        enable_mail=enable_mail,
        enable_calendar=enable_calendar,
        enable_contacts=enable_contacts,
        enable_drive=enable_drive,
        mail_mode=mail_mode,
        mail_folder=mail_folder,
        mail_send=mail_send,
        owner_email=owner_email,
        command_whitelist=whitelist,
        cc_owner=cc_owner,
        trust_require_e2e=trust_require_e2e,
        email=email,
        password=password,
        download_dir=download_dir,
        tutaproxy_path=tutaproxy_path,
        log_level=log_level,
        log_file=log_file,
    )
