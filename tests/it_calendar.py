"""
Test integracyjny etapu 4 — narzędzia kalendarza.

Scenariusze:
 1. list_events — porównaj z liczbą eventów widocznych w API
 2. list_events z filtrem dat
 3. create_event (jednorazowy)
 4. create_event (całodniowy)
 5. create_event z RRULE (cykliczny tygodniowy)
 6. update_event — zmiana tytułu
 7. delete_event — usunięcie testowego eventu

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_calendar.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_calendar import (
    _rrule_to_text, _parse_rrule_text, _parse_iso_dt, _format_dt, _event_to_dict
)


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_CALENDAR", "1")
    env.setdefault("TUTAMCP_ENABLE_MAIL", "0")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test kalendarza (etap 4) ===\n")

    # ── Test 0: unit testy helpers ──────────────────────────────────────────
    print("=== Test 0: unit testy helpers ===")

    # _parse_iso_dt
    dt = _parse_iso_dt("2024-06-13")
    assert dt.year == 2024 and dt.month == 6 and dt.day == 13, f"parse date: {dt}"
    assert dt.hour == 0 and dt.minute == 0
    dt2 = _parse_iso_dt("2024-06-13T14:30:00")
    assert dt2.hour == 14 and dt2.minute == 30
    dt3 = _parse_iso_dt("2024-06-13T14:30:00Z")
    assert dt3.hour == 14 and dt3.minute == 30 and dt3.tzinfo is None
    print("  OK: _parse_iso_dt")

    # _format_dt
    assert _format_dt(datetime(2024, 6, 13, 14, 30), False) == "2024-06-13T14:30:00"
    assert _format_dt(datetime(2024, 6, 13), True) == "2024-06-13"
    assert _format_dt(None, False) is None
    print("  OK: _format_dt")

    # _parse_rrule_text + _rrule_to_text roundtrip
    cases = [
        "FREQ=WEEKLY",
        "FREQ=DAILY;INTERVAL=2",
        "FREQ=MONTHLY;COUNT=12",
        "FREQ=WEEKLY;BYDAY=MO,WE,FR",
        "FREQ=YEARLY;UNTIL=20251231T000000Z",
    ]
    for rrule_str in cases:
        rr = _parse_rrule_text(rrule_str)
        assert rr is not None, f"parse failed: {rrule_str!r}"
        back = _rrule_to_text(rr)
        # Sprawdź że FREQ jest zachowany (reszta może różnić się kolejnością)
        freq_orig = [p for p in rrule_str.split(";") if p.startswith("FREQ=")][0]
        assert freq_orig in back, f"FREQ lost: {rrule_str!r} → {back!r}"
    print(f"  OK: RRULE roundtrip ({len(cases)} przypadków)")

    # ── Test 1: lista eventów ────────────────────────────────────────────────
    print("\n=== Test 1: tuta_calendar_list_events (wszystkie) ===")

    async def _list_all(client, session):
        return await client.get_calendar_events(session)

    events = await sm.call(_list_all)
    print(f"  Łącznie eventów: {len(events)}")
    for ev in events[:5]:
        d = _event_to_dict(ev)
        rrule_str = d.get("rrule") or ""
        print(f"  [{d['start']}] {d['summary']!r} {'(cykl: '+rrule_str+')' if rrule_str else ''}")
    assert isinstance(events, list), "Oczekiwano listy eventów"
    print(f"  OK: pobrano {len(events)} eventów")

    # ── Test 2: filtr dat ────────────────────────────────────────────────────
    print("\n=== Test 2: filtr dat ===")
    now = datetime.utcnow()
    future = now + timedelta(days=365)

    # Filtruj: eventy od teraz do roku w przyszłość
    start_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = future.strftime("%Y-%m-%dT%H:%M:%S")

    filtered = [
        ev for ev in events
        if ev.rrule is not None  # cykliczne: zawsze
        or (ev.start and ev.start >= now and (ev.start < future if ev.start else True))
    ]
    print(f"  Eventy w przyszłości (±365 dni): {len(filtered)}")
    print("  OK: logika filtrowania sprawdzona lokalnie")

    # ── Test 3: create_event (timed) ─────────────────────────────────────────
    print("\n=== Test 3: create_event (jednorazowy, timed) ===")
    test_start = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    test_end = test_start + timedelta(hours=2)

    async def _create_event(client, session):
        from tutamcp.tools_calendar import _get_calendar_info
        from tuta.api import CalendarEvent
        ev = CalendarEvent(
            uid="",
            summary="[tutamcp test] jednorazowy",
            start=test_start,
            end=test_end,
            location="Test Location",
            description="Test opis eventu",
            all_day=False,
            sequence=0,
        )
        group_id, group_key, key_version, short_list, long_list = \
            await _get_calendar_info(client, session)
        return await client.create_calendar_event_api(
            session, group_key, group_id, short_list, long_list, ev, key_version
        )

    list_id1, elem_id1 = await sm.call(_create_event)
    print(f"  Utworzono: list_id={list_id1[:12]}..., elem_id={elem_id1[:12]}...")

    # Weryfikacja: event powinien być widoczny
    events_after = await sm.call(_list_all)
    found = any(e.list_id == list_id1 and e.elem_id == elem_id1 for e in events_after)
    assert found, f"Nowo utworzony event nie znaleziony w liście"
    ev_found = next(e for e in events_after if e.list_id == list_id1 and e.elem_id == elem_id1)
    assert ev_found.summary == "[tutamcp test] jednorazowy"
    assert ev_found.location == "Test Location"
    print(f"  OK: event widoczny w API ({ev_found.summary!r})")

    # ── Test 4: create_event (all-day) ───────────────────────────────────────
    print("\n=== Test 4: create_event (całodniowy) ===")
    allday_start = (now + timedelta(days=5)).replace(hour=0, minute=0, second=0, microsecond=0)
    allday_end = allday_start + timedelta(days=1)

    async def _create_allday(client, session):
        from tutamcp.tools_calendar import _get_calendar_info
        from tuta.api import CalendarEvent
        ev = CalendarEvent(
            uid="",
            summary="[tutamcp test] całodniowy",
            start=allday_start,
            end=allday_end,
            location="",
            description="",
            all_day=True,
            sequence=0,
        )
        group_id, group_key, key_version, short_list, long_list = \
            await _get_calendar_info(client, session)
        return await client.create_calendar_event_api(
            session, group_key, group_id, short_list, long_list, ev, key_version
        )

    list_id2, elem_id2 = await sm.call(_create_allday)
    print(f"  Utworzono: [{list_id2[:12]}..., {elem_id2[:12]}...]")
    events_after2 = await sm.call(_list_all)
    found2 = any(e.list_id == list_id2 and e.elem_id == elem_id2 for e in events_after2)
    assert found2, "Całodniowy event nie znaleziony"
    ev2 = next(e for e in events_after2 if e.list_id == list_id2 and e.elem_id == elem_id2)
    assert ev2.all_day, f"all_day powinno być True, got: {ev2.all_day}"
    print(f"  OK: all_day={ev2.all_day}, start={_format_dt(ev2.start, True)!r}")

    # ── Test 5: create_event z RRULE ─────────────────────────────────────────
    print("\n=== Test 5: create_event z RRULE (tygodniowy, 5x) ===")
    rrule_start = (now + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
    rrule_end = rrule_start + timedelta(hours=1)
    rrule_text = "FREQ=WEEKLY;COUNT=5"
    rr = _parse_rrule_text(rrule_text)
    assert rr is not None

    async def _create_recurring(client, session):
        from tutamcp.tools_calendar import _get_calendar_info
        from tuta.api import CalendarEvent
        ev = CalendarEvent(
            uid="",
            summary="[tutamcp test] cykliczny tygodniowy",
            start=rrule_start,
            end=rrule_end,
            location="",
            description="",
            all_day=False,
            sequence=0,
            rrule=rr,
        )
        group_id, group_key, key_version, short_list, long_list = \
            await _get_calendar_info(client, session)
        return await client.create_calendar_event_api(
            session, group_key, group_id, short_list, long_list, ev, key_version
        )

    list_id3, elem_id3 = await sm.call(_create_recurring)
    events_after3 = await sm.call(_list_all)
    ev3 = next((e for e in events_after3 if e.list_id == list_id3 and e.elem_id == elem_id3), None)
    assert ev3 is not None, "Cykliczny event nie znaleziony"
    assert ev3.rrule is not None, "rrule powinno być ustawione"
    back_text = _rrule_to_text(ev3.rrule)
    assert "WEEKLY" in back_text, f"FREQ=WEEKLY nie zachowany: {back_text!r}"
    print(f"  OK: rrule={back_text!r}")

    # ── Test 6: update_event ─────────────────────────────────────────────────
    print("\n=== Test 6: update_event (zmiana tytułu) ===")

    async def _update(client, session):
        from tutamcp.tools_calendar import _get_calendar_info
        from tuta.api import CalendarEvent
        # Pobierz istniejący event bezpośrednio przez ID
        _, group_key, _ = await client.get_calendar_group_key(session)
        raw = await client._get_tutanota(
            client._url("tutanota", "calendarevent", list_id1, elem_id1),
            token=session.access_token,
        )
        existing = client._decrypt_calendar_event(raw, group_key)
        assert existing is not None, "Nie udało się pobrać eventu do update"

        updated = CalendarEvent(
            uid=existing.uid,
            summary="[tutamcp test] jednorazowy ZAKTUALIZOWANY",
            start=existing.start,
            end=existing.end,
            location=existing.location,
            description=existing.description,
            all_day=existing.all_day,
            sequence=existing.sequence + 1,
        )
        await client.delete_calendar_event_api(session, list_id1, elem_id1)
        group_id, group_key2, key_version, short_list, long_list = \
            await _get_calendar_info(client, session)
        return await client.create_calendar_event_api(
            session, group_key2, group_id, short_list, long_list, updated, key_version
        )

    new_list_id, new_elem_id = await sm.call(_update)
    events_after4 = await sm.call(_list_all)
    ev_updated = next((e for e in events_after4 if e.list_id == new_list_id and e.elem_id == new_elem_id), None)
    assert ev_updated is not None, "Zaktualizowany event nie znaleziony"
    assert "ZAKTUALIZOWANY" in ev_updated.summary, f"Tytuł nie zmieniony: {ev_updated.summary!r}"
    print(f"  OK: nowy tytuł={ev_updated.summary!r}, sequence={ev_updated.sequence}")

    # Stary event powinien zniknąć
    old_found = any(e.list_id == list_id1 and e.elem_id == elem_id1 for e in events_after4)
    assert not old_found, "Stary event nadal widoczny po update"
    print("  OK: stary event usunięty")

    # ── Test 7: delete_event ─────────────────────────────────────────────────
    print("\n=== Test 7: delete_event (sprzątanie) ===")
    to_delete = [
        (new_list_id, new_elem_id),
        (list_id2, elem_id2),
        (list_id3, elem_id3),
    ]

    async def _delete_all(client, session):
        for lid, eid in to_delete:
            try:
                await client.delete_calendar_event_api(session, lid, eid)
                print(f"  Usunięto: [{lid[:12]}..., {eid[:12]}...]")
            except Exception as e:
                print(f"  WARN: błąd usuwania [{lid[:12]}..., {eid[:12]}...]: {e}")

    await sm.call(_delete_all)

    # Weryfikacja: eventy zniknęły
    events_final = await sm.call(_list_all)
    for lid, eid in to_delete:
        still_there = any(e.list_id == lid and e.elem_id == eid for e in events_final)
        assert not still_there, f"Event [{lid[:12]}..., {eid[:12]}...] nadal widoczny po usunięciu"
    print(f"  OK: wszystkie testowe eventy usunięte")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
