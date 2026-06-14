"""
Test integracyjny etapu 5 — narzędzia kontaktów.

Scenariusze:
 1. list — pobierz istniejące kontakty
 2. search — wyszukiwanie po nazwisku / emailu
 3. get — pobierz szczegóły kontaktu
 4. create — utwórz kontakt testowy
 5. update — zmień email i role
 6. delete — usuń kontakt testowy

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_contacts.py
"""

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_contacts import _contact_to_summary, _contact_to_dict, _matches_search


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_CONTACTS", "1")
    env.setdefault("TUTAMCP_ENABLE_MAIL", "0")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test kontaktów (etap 5) ===\n")

    # ── Test 1: lista kontaktów ───────────────────────────────────────────────
    print("=== Test 1: get_contacts (lista) ===")

    async def _list_all(client, session):
        return await client.get_contacts(session)

    contacts = await sm.call(_list_all)
    print(f"  Łącznie kontaktów: {len(contacts)}")
    for c in contacts[:5]:
        s = _contact_to_summary(c)
        print(f"  [{s['name']}] {s['company']!r} {s['email']!r}")
    assert isinstance(contacts, list), "Oczekiwano listy"
    print(f"  OK: pobrano {len(contacts)} kontaktów")

    # ── Test 2: wyszukiwanie ─────────────────────────────────────────────────
    print("\n=== Test 2: _matches_search (unit) ===")

    from tuta.api import Contact, ContactMailAddress
    fake = Contact(
        first_name="Jan", last_name="Kowalski",
        company="ACME Corp", comment="Ważny klient",
        mail_addresses=[ContactMailAddress(type="1", custom_type="", address="jan@acme.com")],
    )
    assert _matches_search(fake, "kowalski"), "Brak dopasowania po nazwisku"
    assert _matches_search(fake, "ACME"), "Brak dopasowania po firmie (case insensitive)"
    assert _matches_search(fake, "jan@acme"), "Brak dopasowania po emailu"
    assert _matches_search(fake, "ważny"), "Brak dopasowania po komentarzu"
    assert not _matches_search(fake, "Nowak"), "Fałszywe dopasowanie"
    print("  OK: _matches_search działa poprawnie")

    # ── Test 3: get szczegóły (jeśli istnieją kontakty) ──────────────────────
    print("\n=== Test 3: get szczegóły (pierwszy kontakt) ===")
    if contacts:
        first = contacts[0]
        async def _get_single(client, session):
            _, group_key, _, _ = await client.get_contact_group_info(session)
            raw = await client._get_tutanota(
                client._url("tutanota", "contact", first.list_id, first.elem_id),
                token=session.access_token,
            )
            return client._decrypt_contact(raw, group_key)

        fetched = await sm.call(_get_single)
        assert fetched is not None, "Nie udało się pobrać kontaktu"
        assert fetched.list_id == first.list_id
        assert fetched.elem_id == first.elem_id
        d = _contact_to_dict(fetched)
        assert "mail_addresses" in d
        print(f"  OK: pobrany kontakt {fetched.first_name!r} {fetched.last_name!r}, "
              f"emails={[m['address'] for m in d['mail_addresses']]}")
    else:
        print("  SKIP: brak kontaktów do pobrania")

    # ── Test 4: create_contact ───────────────────────────────────────────────
    print("\n=== Test 4: create_contact ===")

    from tuta.api import Contact, ContactMailAddress, ContactPhoneNumber

    new_contact = Contact(
        first_name="Test",
        last_name="TutaMCP",
        company="tutamcp-tests",
        role="Test Engineer",
        mail_addresses=[ContactMailAddress(type="1", custom_type="", address="test@tutamcp.example")],
        phone_numbers=[ContactPhoneNumber(type="2", custom_type="", number="+48123456789")],
        comment="Kontakt testowy — do usunięcia",
    )

    async def _create(client, session):
        list_id, group_key, group_id, key_version = \
            await client.get_contact_group_info(session)
        return await client.create_contact_api(
            session, new_contact, list_id, group_key, group_id, key_version
        )

    new_list_id, new_elem_id = await sm.call(_create)
    print(f"  Utworzono: [{new_list_id[:12]}..., {new_elem_id[:12]}...]")

    # Weryfikacja: widoczny w liście
    contacts2 = await sm.call(_list_all)
    created = next((c for c in contacts2 if c.elem_id == new_elem_id), None)
    assert created is not None, "Nowy kontakt nie znaleziony w liście"
    assert created.last_name == "TutaMCP"
    assert any(m.address == "test@tutamcp.example" for m in created.mail_addresses)
    print(f"  OK: kontakt widoczny, email={[m.address for m in created.mail_addresses]!r}")

    # ── Test 5: update_contact ───────────────────────────────────────────────
    print("\n=== Test 5: update_contact ===")

    updated_contact = Contact(
        list_id=new_list_id,
        elem_id=new_elem_id,
        first_name="Test",
        last_name="TutaMCP",
        company="tutamcp-tests",
        role="Senior Test Engineer",
        mail_addresses=[
            ContactMailAddress(type="1", custom_type="", address="test-updated@tutamcp.example")
        ],
        phone_numbers=created.phone_numbers,
        comment="Kontakt testowy — zaktualizowany",
    )

    async def _update(client, session):
        _, group_key, _, key_version = await client.get_contact_group_info(session)
        await client.update_contact_api(session, updated_contact, group_key, key_version)

    await sm.call(_update)

    # Weryfikacja
    contacts3 = await sm.call(_list_all)
    updated = next((c for c in contacts3 if c.elem_id == new_elem_id), None)
    assert updated is not None, "Zaktualizowany kontakt nie znaleziony"
    assert updated.role == "Senior Test Engineer", f"role nie zmieniony: {updated.role!r}"
    assert any(m.address == "test-updated@tutamcp.example" for m in updated.mail_addresses), \
        f"email nie zmieniony: {[m.address for m in updated.mail_addresses]}"
    print(f"  OK: role={updated.role!r}, email={[m.address for m in updated.mail_addresses]!r}")

    # ── Test 6: delete_contact ───────────────────────────────────────────────
    print("\n=== Test 6: delete_contact ===")

    async def _delete(client, session):
        await client.delete_contact_api(session, new_list_id, new_elem_id)

    await sm.call(_delete)

    contacts4 = await sm.call(_list_all)
    still_there = any(c.elem_id == new_elem_id for c in contacts4)
    assert not still_there, "Kontakt nadal widoczny po usunięciu"
    print("  OK: kontakt usunięty")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
