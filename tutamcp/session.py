"""
SessionManager — cykl życia sesji TutaClient dla długo żyjącego serwera MCP.

Zasady:
- jedna sesja na proces (singleton na TutaClient + Session)
- lazy login — pierwsze wywołanie call() loguje, nie start serwera
- 440 SessionExpired lub 401 → unieważnij sesję, zaloguj ponownie, ponów raz
- zamknięcie serwera → logout() (DELETE /sys/session), bez tego rosną aktywne
  sesje w UI Tuty
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from tuta.api import TutaAPIError, TutaClient, Session

from .config import Config

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: Optional[TutaClient] = None
        self._session: Optional[Session] = None
        # blokada chroni _client i _session przed równoległymi coroutines
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------------------
    # Publiczne API
    # -----------------------------------------------------------------------

    async def get(self) -> tuple[TutaClient, Session]:
        """Zwraca aktywną parę (client, session). Loguje przy pierwszym wywołaniu."""
        async with self._lock:
            if self._client is None:
                await self._do_login()
            assert self._client is not None and self._session is not None
            return self._client, self._session

    async def call(
        self,
        coro_fn: Callable[[TutaClient, Session], Coroutine[Any, Any, Any]],
    ) -> Any:
        """
        Wykonuje coro_fn(client, session). Przy 440 lub 401 unieważnia sesję,
        loguje ponownie i ponawia raz.
        """
        client, session = await self.get()
        try:
            return await coro_fn(client, session)
        except TutaAPIError as e:
            if e.status_code in (440, 401):
                logger.info(
                    "SessionManager: HTTP %d (%s), invalidate + retry",
                    e.status_code,
                    "SessionExpired" if e.status_code == 440 else "Unauthorized",
                )
                await self.invalidate()
                client, session = await self.get()
                return await coro_fn(client, session)
            raise

    async def invalidate(self) -> None:
        """Unieważnia bieżącą sesję bez wylogowania (np. po 440 — token już nieważny)."""
        async with self._lock:
            await self._close_client(do_logout=False)

    async def close(self) -> None:
        """Graceful shutdown — wywołaj przy zamykaniu serwera."""
        async with self._lock:
            await self._close_client(do_logout=True)

    # -----------------------------------------------------------------------
    # Prywatne
    # -----------------------------------------------------------------------

    async def _do_login(self) -> None:
        """Tworzy TutaClient i loguje się. Wymaga trzymanego _lock."""
        assert self._config.email and self._config.password, (
            "Brak danych logowania w Config — SessionManager nie powinien "
            "być tworzony bez włączonego modułu"
        )
        client = TutaClient()
        await client.__aenter__()
        try:
            session = await client.login(self._config.email, self._config.password)
        except Exception:
            await client.__aexit__(None, None, None)
            raise
        self._client = client
        self._session = session
        logger.info("SessionManager: zalogowano jako %s", session.user_email)

    async def _close_client(self, do_logout: bool) -> None:
        """Zamyka klienta. do_logout=True → najpierw DELETE /sys/session."""
        if self._client is None:
            return
        if do_logout and self._session is not None:
            try:
                await self._client.logout(self._session)
                logger.info("SessionManager: wylogowano")
            except Exception as exc:
                logger.warning("SessionManager: logout nieudany: %s", exc)
        await self._client.__aexit__(None, None, None)
        self._client = None
        self._session = None
