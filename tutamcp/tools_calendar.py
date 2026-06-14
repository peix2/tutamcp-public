"""
Narzędzia MCP dla kalendarza Tuta.

Rejestrowane warunkowo gdy TUTAMCP_ENABLE_CALENDAR=1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from tutamcp.errors import safe_call as _safe_call

logger = logging.getLogger(__name__)

# Mapowania RRULE ↔ Tuta RepeatPeriod/ByRule (tożsame z caldav_server.py)
_FREQ_TO_TUTA = {"DAILY": "0", "WEEKLY": "1", "MONTHLY": "2", "YEARLY": "3"}
_TUTA_TO_FREQ = {v: k for k, v in _FREQ_TO_TUTA.items()}
_BY_TO_TUTA = {
    "BYDAY": "2", "BYMONTHDAY": "3", "BYYEARDAY": "4",
    "BYWEEKNO": "5", "BYMONTH": "6", "BYSETPOS": "7", "WKST": "8",
}
_TUTA_TO_BY = {v: k for k, v in _BY_TO_TUTA.items()}


def _rrule_to_text(rr) -> str:
    """Konwertuje RepeatRule → string RRULE (bez prefiksu 'RRULE:')."""
    freq = _TUTA_TO_FREQ.get(rr.frequency, "DAILY")
    parts = [f"FREQ={freq}"]
    if rr.interval and rr.interval != "1":
        parts.append(f"INTERVAL={rr.interval}")
    if rr.end_type == "1" and rr.end_value:
        parts.append(f"COUNT={rr.end_value}")
    elif rr.end_type == "2" and rr.end_value:
        # Tuta przechowuje ekskluzywny timestamp ms → iCal: inkluzywny (cofamy 1s)
        until_ms = int(rr.end_value)
        until_dt = datetime.utcfromtimestamp((until_ms - 1000) / 1000).replace(tzinfo=timezone.utc)
        parts.append(f"UNTIL={until_dt.strftime('%Y%m%dT%H%M%SZ')}")
    # Advanced rules: grupuj po typie → BYDAY=MO,WE itd.
    by_type: dict[str, list[str]] = {}
    for ar in (rr.advanced_rules or []):
        ical_key = _TUTA_TO_BY.get(ar.rule_type, "")
        if ical_key:
            by_type.setdefault(ical_key, []).append(ar.interval)
    for ical_key, vals in sorted(by_type.items()):
        parts.append(f"{ical_key}={','.join(vals)}")
    return ";".join(parts)


def _parse_rrule_text(text: str) -> Any:
    """
    Parsuje string RRULE → RepeatRule.
    Akceptuje format z lub bez prefiksu 'RRULE:'.
    Zwraca None gdy FREQ nieznany lub niepoprawny format.
    """
    try:
        from tuta.api import RepeatRule, RepeatRuleAdvanced
    except ImportError:
        return None

    text = text.strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]

    parts: dict[str, str] = {}
    for part in text.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.upper()] = v

    freq = _FREQ_TO_TUTA.get(parts.get("FREQ", "").upper())
    if not freq:
        return None

    interval = parts.get("INTERVAL", "1")
    end_type = "0"
    end_value = None

    if "COUNT" in parts:
        end_type = "1"
        end_value = parts["COUNT"]
    elif "UNTIL" in parts:
        end_type = "2"
        until_str = parts["UNTIL"]
        try:
            if "T" in until_str:
                fmt = "%Y%m%dT%H%M%SZ" if until_str.endswith("Z") else "%Y%m%dT%H%M%S"
                until_dt = datetime.strptime(until_str, fmt).replace(tzinfo=timezone.utc)
                # iCal inkluzywny → Tuta ekskluzywny (+1s)
                end_value = str(int(until_dt.timestamp() * 1000) + 1000)
            else:
                until_dt = datetime.strptime(until_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                end_value = str(int((until_dt + timedelta(days=1)).timestamp() * 1000))
        except Exception:
            pass

    advanced = []
    for ical_key, rule_type in _BY_TO_TUTA.items():
        raw_val = parts.get(ical_key, "")
        if raw_val:
            for v in raw_val.split(","):
                if v:
                    advanced.append(RepeatRuleAdvanced(rule_type=rule_type, interval=v))

    return RepeatRule(
        frequency=freq,
        end_type=end_type,
        end_value=end_value,
        interval=interval,
        time_zone="UTC",
        excluded_dates=[],
        advanced_rules=advanced,
    )


def _parse_iso_dt(s: str) -> datetime:
    """
    Parsuje ISO 8601 datetime lub datę → naive datetime UTC.
    Akceptuje: YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YYYY-MM-DDTHH:MM:SSZ, offset +HH:MM.
    """
    s = s.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return datetime.strptime(s, "%Y-%m-%d")  # midnight, treated as UTC
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        raise ValueError(
            f"Nieprawidłowy format daty: {s!r}. Użyj ISO 8601: YYYY-MM-DD lub YYYY-MM-DDTHH:MM:SS"
        )


def _format_dt(dt: Optional[datetime], all_day: bool) -> Optional[str]:
    """Formatuje datetime → ISO string dla MCP response."""
    if dt is None:
        return None
    if all_day:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _event_to_dict(ev) -> dict:
    """Konwertuje CalendarEvent → słownik dla MCP response."""
    return {
        "list_id": ev.list_id,
        "elem_id": ev.elem_id,
        "uid": ev.uid,
        "summary": ev.summary,
        "start": _format_dt(ev.start, ev.all_day),
        "end": _format_dt(ev.end, ev.all_day),
        "all_day": ev.all_day,
        "location": ev.location or "",
        "description": ev.description or "",
        "rrule": _rrule_to_text(ev.rrule) if ev.rrule else None,
        "recurrence_id": _format_dt(ev.recurrence_id, ev.all_day) if ev.recurrence_id else None,
        "sequence": ev.sequence,
    }


async def _get_calendar_info(client, session) -> tuple:
    """Pobiera (group_id, group_key, key_version, short_list_id, long_list_id)."""
    group_id, group_key, key_version = await client.get_calendar_group_key(session)
    root = await client._get_tutanota(
        client._url("tutanota", "calendargrouproot", group_id),
        token=session.access_token,
    )

    def _unpack(val):
        if isinstance(val, list):
            return val[-1] if val else ""
        return val or ""

    short_list = _unpack(root.get("954", ""))
    long_list = _unpack(root.get("955", ""))
    return group_id, group_key, key_version, short_list, long_list


def register_calendar_tools(mcp, cfg, sm) -> None:
    """Rejestruje narzędzia kalendarza w serwerze FastMCP."""

    @mcp.tool()
    async def tuta_calendar_list_events(
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Lists calendar events, optionally filtered by date range.

        Parameters:
        - start: Filter start (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).
                 Events ending before this are excluded.
        - end:   Filter end (ISO 8601). Events starting after this are excluded.

        Returns list of events. Each event includes: list_id, elem_id (needed for
        update/delete), uid, summary, start, end, all_day, location, description,
        rrule (RRULE string if recurring), recurrence_id (if occurrence exception).

        Note: recurring events (with rrule field) are always included regardless of
        date filters — individual occurrences are not expanded. The model should
        interpret the rrule field to determine when occurrences fall.
        """
        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None
        if start:
            try:
                start_dt = _parse_iso_dt(start)
            except ValueError as e:
                return {"error": str(e)}
        if end:
            try:
                end_dt = _parse_iso_dt(end)
            except ValueError as e:
                return {"error": str(e)}

        async def _get(client, session):
            return await client.get_calendar_events(session)

        events, err = await _safe_call(sm, _get)
        if err:
            return err

        result = []
        for ev in events:
            # Eventy cykliczne: zawsze dołącz (nie rozwijamy RRULE)
            if ev.rrule is not None:
                result.append(_event_to_dict(ev))
                continue
            # Filtr overlap: ev.start < end_dt AND ev.end > start_dt
            ev_start = ev.start
            ev_end = ev.end
            if ev_start and ev_start.tzinfo is not None:
                ev_start = ev_start.replace(tzinfo=None)
            if ev_end and ev_end.tzinfo is not None:
                ev_end = ev_end.replace(tzinfo=None)
            if start_dt and ev_end and ev_end <= start_dt:
                continue
            if end_dt and ev_start and ev_start >= end_dt:
                continue
            result.append(_event_to_dict(ev))

        result.sort(key=lambda e: e.get("start") or "")
        return {"events": result, "count": len(result)}

    @mcp.tool()
    async def tuta_calendar_create_event(
        summary: str,
        start: str,
        end: str,
        all_day: bool = False,
        description: str = "",
        location: str = "",
        rrule: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Creates a new calendar event.

        Parameters:
        - summary:     Event title (required).
        - start:       Start date/time in ISO 8601. Use YYYY-MM-DD for all-day events,
                       YYYY-MM-DDTHH:MM:SS for timed events.
        - end:         End date/time in ISO 8601. For all-day events use the day AFTER
                       the last day (exclusive end, as per iCalendar standard).
        - all_day:     True for all-day event. Auto-detected when start has no time component.
        - description: Event description (optional).
        - location:    Event location (optional).
        - rrule:       Recurrence rule string without 'RRULE:' prefix, e.g.
                       'FREQ=WEEKLY;BYDAY=MO,WE' or 'FREQ=MONTHLY;INTERVAL=2' (optional).

        Returns list_id and elem_id of the created event (needed for update/delete).
        """
        try:
            start_dt = _parse_iso_dt(start)
            end_dt = _parse_iso_dt(end)
        except ValueError as e:
            return {"error": str(e)}

        is_all_day = all_day or (len(start.strip()) == 10)

        repeat_rule = None
        if rrule:
            repeat_rule = _parse_rrule_text(rrule)
            if repeat_rule is None:
                return {
                    "error": f"Nieprawidłowy format RRULE: {rrule!r}. "
                             "Przykład: FREQ=WEEKLY;BYDAY=MO lub FREQ=MONTHLY;INTERVAL=2"
                }

        try:
            from tuta.api import CalendarEvent
        except ImportError as e:
            return {"error": f"Błąd importu tutaproxy: {e}"}

        ev = CalendarEvent(
            uid="",
            summary=summary,
            start=start_dt,
            end=end_dt,
            location=location,
            description=description,
            all_day=is_all_day,
            sequence=0,
            rrule=repeat_rule,
        )

        async def _create(client, session):
            group_id, group_key, key_version, short_list, long_list = \
                await _get_calendar_info(client, session)
            return await client.create_calendar_event_api(
                session, group_key, group_id, short_list, long_list, ev, key_version
            )

        result, err = await _safe_call(sm, _create)
        if err:
            return err
        list_id, elem_id = result
        logger.info("tuta_calendar_create_event: %r → [%s, %s]", summary, list_id[:12], elem_id[:12])
        return {
            "status": "created",
            "list_id": list_id,
            "elem_id": elem_id,
            "summary": summary,
            "start": _format_dt(start_dt, is_all_day),
            "end": _format_dt(end_dt, is_all_day),
            "all_day": is_all_day,
        }

    @mcp.tool()
    async def tuta_calendar_delete_event(
        list_id: str,
        elem_id: str,
    ) -> dict[str, Any]:
        """
        Permanently deletes a calendar event.

        Parameters:
        - list_id: Event list ID (from tuta_calendar_list_events or create).
        - elem_id: Event element ID.

        Warning: deleting a recurring event (with rrule) deletes the master event
        and all its occurrences. Individual occurrence exceptions (recurrence_id ≠ null)
        can be deleted independently.
        """
        async def _delete(client, session):
            await client.delete_calendar_event_api(session, list_id, elem_id)

        _, err = await _safe_call(sm, _delete)
        if err:
            return err
        logger.info("tuta_calendar_delete_event: [%s, %s]", list_id[:12], elem_id[:12])
        return {"status": "deleted", "list_id": list_id, "elem_id": elem_id}

    @mcp.tool()
    async def tuta_calendar_update_event(
        list_id: str,
        elem_id: str,
        summary: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        all_day: Optional[bool] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        rrule: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Updates a calendar event (implemented as delete + recreate).

        Provide only fields you want to change; others are preserved from the existing event.

        Parameters:
        - list_id:     Event list ID.
        - elem_id:     Event element ID.
        - summary:     New title (optional).
        - start:       New start in ISO 8601 (optional).
        - end:         New end in ISO 8601 (optional).
        - all_day:     Override all-day flag (optional).
        - description: New description (optional).
        - location:    New location (optional).
        - rrule:       New recurrence rule (optional). Pass empty string "" to remove recurrence.

        Returns new list_id and elem_id (these change after update since Tuta recreates the event).

        Limitation: editing a single occurrence of a recurring series is not supported.
        Updating a recurring event updates all occurrences.
        """
        # Pobierz istniejący event bezpośrednio przez ID
        async def _fetch(client, session):
            _, group_key, _ = await client.get_calendar_group_key(session)
            raw = await client._get_tutanota(
                client._url("tutanota", "calendarevent", list_id, elem_id),
                token=session.access_token,
            )
            return client._decrypt_calendar_event(raw, group_key)

        existing, err = await _safe_call(sm, _fetch)
        if err:
            return err
        if existing is None:
            return {"error": f"Event nie znaleziony lub błąd deszyfrowania: [{list_id}, {elem_id}]"}

        # Nałóż zmiany
        new_summary = summary if summary is not None else existing.summary
        new_description = description if description is not None else existing.description
        new_location = location if location is not None else existing.location
        new_all_day = all_day if all_day is not None else existing.all_day

        new_start = existing.start
        if start is not None:
            try:
                new_start = _parse_iso_dt(start)
                if len(start.strip()) == 10:
                    new_all_day = True
            except ValueError as e:
                return {"error": str(e)}

        new_end = existing.end
        if end is not None:
            try:
                new_end = _parse_iso_dt(end)
            except ValueError as e:
                return {"error": str(e)}

        new_rrule = existing.rrule
        if rrule is not None:
            if rrule == "":
                new_rrule = None
            else:
                new_rrule = _parse_rrule_text(rrule)
                if new_rrule is None:
                    return {"error": f"Nieprawidłowy format RRULE: {rrule!r}"}

        try:
            from tuta.api import CalendarEvent
        except ImportError as e:
            return {"error": f"Błąd importu tutaproxy: {e}"}

        new_ev = CalendarEvent(
            uid=existing.uid,
            summary=new_summary,
            start=new_start,
            end=new_end,
            location=new_location,
            description=new_description,
            all_day=new_all_day,
            sequence=existing.sequence + 1,
            rrule=new_rrule,
        )

        async def _update(client, session):
            # Usuń stary, utwórz nowy
            await client.delete_calendar_event_api(session, list_id, elem_id)
            group_id, group_key, key_version, short_list, long_list = \
                await _get_calendar_info(client, session)
            return await client.create_calendar_event_api(
                session, group_key, group_id, short_list, long_list, new_ev, key_version
            )

        result, err = await _safe_call(sm, _update)
        if err:
            return err
        new_list_id, new_elem_id = result
        logger.info("tuta_calendar_update_event: [%s,%s] → [%s,%s]",
                    list_id[:12], elem_id[:12], new_list_id[:12], new_elem_id[:12])
        return {
            "status": "updated",
            "list_id": new_list_id,
            "elem_id": new_elem_id,
            "summary": new_summary,
            "start": _format_dt(new_start, new_all_day),
            "end": _format_dt(new_end, new_all_day),
            "all_day": new_all_day,
        }
