"""
Egzekwowanie polityki dostępu do poczty.

Dwa poziomy kontroli:
 1. Które narzędzia są zarejestrowane w FastMCP (narzędzia zablokowane nie istnieją dla modelu).
 2. Sprawdzenie folderu/dostępu przy wywołaniu narzędzia — dla trybu FOLDER.

Tryby konta (MailMode):
  DEDICATED — pełny dostęp, mail_send domyślnie FULL.
  SHARED    — pełny dostęp, mail_send domyślnie REPLY_ONLY.
  FOLDER    — tylko narzędzia czytania/operacji na mailach w skonfigurowanym folderze;
              wymuszone REPLY_ONLY; brak CRUD folderów.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config, MailMode, MailSend

# Narzędzia zawsze dostępne gdy enable_mail=True (z wyjątkami trybów niżej)
_MAIL_READ_TOOLS = {
    "tuta_mail_list_folders",
    "tuta_mail_list",
    "tuta_mail_read",
    "tuta_mail_get_attachment",
}
_MAIL_ACTION_TOOLS = {
    "tuta_mail_reply",
    "tuta_mail_move",
    "tuta_mail_delete",
    "tuta_mail_mark",
}
# Narzędzia CRUD folderów — tylko w trybach DEDICATED i SHARED
_MAIL_FOLDER_MGMT_TOOLS = {
    "tuta_mail_folder_create",
    "tuta_mail_folder_rename",
    "tuta_mail_folder_delete",
}


def allowed_tools(cfg: "Config") -> set[str]:
    """
    Zwraca zbiór nazw narzędzi mail dozwolonych przy bieżącej konfiguracji.
    Narzędzia spoza zbioru nie powinny być rejestrowane w FastMCP.
    """
    if not cfg.enable_mail:
        return set()

    from .config import MailMode, MailSend

    tools: set[str] = set()
    tools |= _MAIL_READ_TOOLS
    tools |= _MAIL_ACTION_TOOLS

    if cfg.mail_send == MailSend.FULL:
        tools.add("tuta_mail_send")

    if cfg.mail_mode != MailMode.FOLDER:
        tools |= _MAIL_FOLDER_MGMT_TOOLS

    return tools


def check_folder_access(cfg: "Config", folder_mail_list_id: str) -> bool:
    """
    W trybie FOLDER: sprawdź czy folder_mail_list_id to skonfigurowany folder.
    W pozostałych trybach zawsze zwraca True.

    cfg.mail_folder powinno przechowywać mail_list_id folderu (pole 'id'
    z tuta_mail_list_folders). Można też porównywać po nazwie, ale ID jest
    jednoznaczne i nie wymaga deszyfrowania.
    """
    from .config import MailMode

    if cfg.mail_mode != MailMode.FOLDER:
        return True

    if not cfg.mail_folder:
        return False

    return folder_mail_list_id == cfg.mail_folder


def folder_access_error(cfg: "Config") -> dict:
    """Komunikat błędu dla odmowy dostępu do folderu w trybie FOLDER."""
    return {
        "error": (
            f"Tryb FOLDER: dostęp tylko do skonfigurowanego folderu "
            f"(mail_list_id={cfg.mail_folder!r}). "
            "Użyj tuta_mail_list_folders aby zobaczyć dostępne ID."
        )
    }
