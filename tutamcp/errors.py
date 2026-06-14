"""
Pomocnicze funkcje obsługi błędów dla narzędzi MCP.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


async def safe_call(sm, coro_fn) -> Tuple[Any, Optional[dict]]:
    """
    Wykonuje sm.call(coro_fn). Przy TutaAPIError zwraca (None, error_dict).
    Przy sukcesie zwraca (result, None).
    Użycie: result, err = await safe_call(sm, fn); if err: return err
    """
    try:
        result = await sm.call(coro_fn)
        return result, None
    except Exception as e:
        try:
            from tuta.api import TutaAPIError
            if isinstance(e, TutaAPIError):
                return None, tuta_api_error_to_dict(e)
        except ImportError:
            pass
        raise


def tuta_api_error_to_dict(e: Exception) -> dict:
    """
    Konwertuje TutaAPIError (lub inny wyjątek) na czytelny słownik błędu
    zwracany przez narzędzia MCP.

    Komentarze dla modelu:
    - 429: serwer Tuty przeciążony lub przekroczony limit — poczekaj chwilę
    - 401/440: sesja wygasła (SessionManager powinien automatycznie ponowić)
    - 403: brak uprawnień do zasobu
    - 404: zasób nie istnieje
    - 5xx: błąd serwera Tuty
    """
    status = getattr(e, "status_code", 0)

    if status == 429:
        return {
            "error": "Serwer Tuty zwrócił 429 (Too Many Requests). "
                     "Poczekaj chwilę i spróbuj ponownie.",
            "error_code": 429,
        }
    if status in (401, 440):
        return {
            "error": "Sesja Tuty wygasła lub token nieważny (HTTP {status}). "
                     "Spróbuj ponownie — serwer automatycznie zaloguje się ponownie.",
            "error_code": status,
        }
    if status == 403:
        return {
            "error": f"Brak uprawnień (HTTP 403). Sprawdź konfigurację konta lub politykę dostępu.",
            "error_code": 403,
        }
    if status == 404:
        return {
            "error": f"Zasób nie znaleziony (HTTP 404): {str(e)}",
            "error_code": 404,
        }
    if status >= 500:
        return {
            "error": f"Błąd serwera Tuty (HTTP {status}). Spróbuj ponownie za chwilę.",
            "error_code": status,
        }
    if status > 0:
        return {
            "error": f"Błąd API Tuty (HTTP {status}): {str(e)}",
            "error_code": status,
        }
    # Inny wyjątek (np. sieciowy, dekrypcja)
    return {
        "error": f"Błąd wewnętrzny: {type(e).__name__}: {e}",
    }
