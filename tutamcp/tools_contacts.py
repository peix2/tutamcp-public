"""
Narzędzia MCP dla kontaktów Tuta.

Rejestrowane warunkowo gdy TUTAMCP_ENABLE_CONTACTS=1.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from tutamcp.errors import safe_call as _safe_call

logger = logging.getLogger(__name__)

# Typy adresów e-mail / telefonów / adresów (stałe Tuta)
_MAIL_TYPE = {"private": "0", "work": "1", "other": "2", "custom": "3"}
_PHONE_TYPE = {"private": "0", "work": "1", "mobile": "2", "fax": "3", "other": "4", "custom": "5"}
_ADDR_TYPE  = {"private": "0", "work": "1", "other": "2", "custom": "3"}


def _contact_to_summary(c) -> dict:
    """Skrócony opis kontaktu (lista)."""
    main_email = c.mail_addresses[0].address if c.mail_addresses else ""
    return {
        "list_id": c.list_id,
        "elem_id": c.elem_id,
        "name": f"{c.first_name} {c.last_name}".strip() or c.nickname or c.company or "(brak nazwy)",
        "company": c.company or "",
        "email": main_email,
    }


def _contact_to_dict(c) -> dict:
    """Pełny opis kontaktu."""
    return {
        "list_id": c.list_id,
        "elem_id": c.elem_id,
        "first_name": c.first_name or "",
        "last_name": c.last_name or "",
        "middle_name": c.middle_name or "",
        "title": c.title or "",
        "name_suffix": c.name_suffix or "",
        "nickname": c.nickname or "",
        "company": c.company or "",
        "department": c.department or "",
        "role": c.role or "",
        "mail_addresses": [
            {"type": m.type, "address": m.address, "custom_type": m.custom_type}
            for m in (c.mail_addresses or [])
        ],
        "phone_numbers": [
            {"type": p.type, "number": p.number, "custom_type": p.custom_type}
            for p in (c.phone_numbers or [])
        ],
        "addresses": [
            {"type": a.type, "address": a.address, "custom_type": a.custom_type}
            for a in (c.addresses or [])
        ],
        "websites": [
            {"type": t, "url": u} for t, u in (c.websites or [])
        ],
        "social_ids": [
            {"type": t, "id": sid} for t, sid in (c.social_ids or [])
        ],
        "birthday": c.birthday_iso or "",
        "comment": c.comment or "",
    }


def _matches_search(c, query: str) -> bool:
    """Sprawdza czy kontakt pasuje do zapytania (case-insensitive)."""
    q = query.lower()
    fields = [
        c.first_name, c.last_name, c.middle_name, c.nickname,
        c.company, c.department, c.role, c.comment,
    ]
    for f in fields:
        if f and q in f.lower():
            return True
    for m in (c.mail_addresses or []):
        if m.address and q in m.address.lower():
            return True
    for p in (c.phone_numbers or []):
        if p.number and q in p.number.lower():
            return True
    return False


def register_contacts_tools(mcp, cfg, sm) -> None:
    """Rejestruje narzędzia kontaktów w serwerze FastMCP."""

    @mcp.tool()
    async def tuta_contacts_list(
        search: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Lists contacts, optionally filtered by a search query.

        Parameters:
        - search: Case-insensitive search in name, company, email, phone, comment (optional).
        - limit:  Maximum number of results to return (default 50, max 500).

        Returns a list of summaries with: list_id, elem_id, name, company, email.
        Use tuta_contacts_get to retrieve full details for a specific contact.
        """
        limit = max(1, min(500, limit))

        async def _get(client, session):
            return await client.get_contacts(session)

        contacts, err = await _safe_call(sm, _get)
        if err:
            return err

        if search:
            contacts = [c for c in contacts if _matches_search(c, search)]

        # Sortuj alfabetycznie po nazwisku + imieniu
        contacts.sort(key=lambda c: (c.last_name.lower(), c.first_name.lower()))
        contacts = contacts[:limit]

        return {
            "contacts": [_contact_to_summary(c) for c in contacts],
            "count": len(contacts),
            "has_more": len(contacts) == limit,
        }

    @mcp.tool()
    async def tuta_contacts_get(
        list_id: str,
        elem_id: str,
    ) -> dict[str, Any]:
        """
        Returns full details for a specific contact.

        Parameters:
        - list_id: Contact list ID (from tuta_contacts_list).
        - elem_id: Contact element ID.

        Returns all contact fields: name components, company, mail_addresses,
        phone_numbers, addresses, websites, social_ids, birthday, comment.
        """
        async def _fetch(client, session):
            _, group_key, _, _ = await client.get_contact_group_info(session)
            raw = await client._get_tutanota(
                client._url("tutanota", "contact", list_id, elem_id),
                token=session.access_token,
            )
            return client._decrypt_contact(raw, group_key)

        contact, err = await _safe_call(sm, _fetch)
        if err:
            return err
        if contact is None:
            return {"error": f"Kontakt nie znaleziony lub błąd deszyfrowania: [{list_id}, {elem_id}]"}
        return _contact_to_dict(contact)

    @mcp.tool()
    async def tuta_contacts_create(
        first_name: str = "",
        last_name: str = "",
        company: str = "",
        email: str = "",
        email_type: str = "work",
        phone: str = "",
        phone_type: str = "mobile",
        middle_name: str = "",
        nickname: str = "",
        title: str = "",
        department: str = "",
        role: str = "",
        birthday: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        """
        Creates a new contact.

        Parameters:
        - first_name:  First name.
        - last_name:   Last name.
        - company:     Company/organization.
        - email:       Primary email address (optional).
        - email_type:  Email type: 'work', 'private', 'other', 'custom' (default: 'work').
        - phone:       Primary phone number (optional).
        - phone_type:  Phone type: 'mobile', 'work', 'private', 'fax', 'other', 'custom' (default: 'mobile').
        - middle_name: Middle name (optional).
        - nickname:    Nickname (optional).
        - title:       Honorific title e.g. 'Dr', 'Prof' (optional).
        - department:  Department (optional).
        - role:        Job title/role (optional).
        - birthday:    Birthday in ISO format YYYY-MM-DD (optional).
        - comment:     Notes/comment (optional).

        At least one of first_name, last_name, or company must be provided.
        Returns list_id and elem_id of the created contact.
        """
        if not first_name and not last_name and not company:
            return {"error": "Podaj co najmniej first_name, last_name lub company"}

        try:
            from tuta.api import Contact, ContactMailAddress, ContactPhoneNumber
        except ImportError as e:
            return {"error": f"Błąd importu tutaproxy: {e}"}

        mail_addresses = []
        if email:
            mail_type = _MAIL_TYPE.get(email_type.lower(), "1")
            mail_addresses.append(ContactMailAddress(type=mail_type, custom_type="", address=email))

        phone_numbers = []
        if phone:
            ph_type = _PHONE_TYPE.get(phone_type.lower(), "2")
            phone_numbers.append(ContactPhoneNumber(type=ph_type, custom_type="", number=phone))

        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            title=title,
            nickname=nickname,
            company=company,
            department=department,
            role=role,
            mail_addresses=mail_addresses,
            phone_numbers=phone_numbers,
            birthday_iso=birthday,
            comment=comment,
        )

        async def _create(client, session):
            list_id, group_key, group_id, key_version = \
                await client.get_contact_group_info(session)
            return await client.create_contact_api(
                session, contact, list_id, group_key, group_id, key_version
            )

        result, err = await _safe_call(sm, _create)
        if err:
            return err
        new_list_id, new_elem_id = result
        name = f"{first_name} {last_name}".strip() or company
        logger.info("tuta_contacts_create: %r → [%s, %s]", name, new_list_id[:12], new_elem_id[:12])
        return {
            "status": "created",
            "list_id": new_list_id,
            "elem_id": new_elem_id,
            "name": name,
        }

    @mcp.tool()
    async def tuta_contacts_update(
        list_id: str,
        elem_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company: Optional[str] = None,
        email: Optional[str] = None,
        email_type: str = "work",
        phone: Optional[str] = None,
        phone_type: str = "mobile",
        middle_name: Optional[str] = None,
        nickname: Optional[str] = None,
        title: Optional[str] = None,
        department: Optional[str] = None,
        role: Optional[str] = None,
        birthday: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Updates an existing contact.

        Provide only the fields you want to change; others are preserved.

        Parameters:
        - list_id, elem_id: Contact identifiers.
        - first_name, last_name, company, middle_name, nickname, title,
          department, role, birthday, comment: Simple string fields (optional).
        - email:       Replaces the first email address, or adds one if none exist.
                       Pass empty string "" to remove all email addresses.
        - email_type:  Type for the new/replaced email (default: 'work').
        - phone:       Replaces the first phone number, or adds one if none exist.
                       Pass empty string "" to remove all phone numbers.
        - phone_type:  Type for the new/replaced phone (default: 'mobile').
        """
        # Pobierz istniejący kontakt
        async def _fetch(client, session):
            _, group_key, _, _ = await client.get_contact_group_info(session)
            raw = await client._get_tutanota(
                client._url("tutanota", "contact", list_id, elem_id),
                token=session.access_token,
            )
            return client._decrypt_contact(raw, group_key)

        existing, err = await _safe_call(sm, _fetch)
        if err:
            return err
        if existing is None:
            return {"error": f"Kontakt nie znaleziony: [{list_id}, {elem_id}]"}

        try:
            from tuta.api import Contact, ContactMailAddress, ContactPhoneNumber
        except ImportError as e:
            return {"error": f"Błąd importu tutaproxy: {e}"}

        # Nałóż zmiany na proste pola
        updated = Contact(
            list_id=list_id,
            elem_id=elem_id,
            first_name=first_name if first_name is not None else existing.first_name,
            last_name=last_name if last_name is not None else existing.last_name,
            middle_name=middle_name if middle_name is not None else existing.middle_name,
            title=title if title is not None else existing.title,
            name_suffix=existing.name_suffix,
            nickname=nickname if nickname is not None else existing.nickname,
            company=company if company is not None else existing.company,
            department=department if department is not None else existing.department,
            role=role if role is not None else existing.role,
            mail_addresses=existing.mail_addresses,
            phone_numbers=existing.phone_numbers,
            addresses=existing.addresses,
            websites=existing.websites,
            social_ids=existing.social_ids,
            birthday_iso=birthday if birthday is not None else existing.birthday_iso,
            comment=comment if comment is not None else existing.comment,
        )

        # Obsłuż email: "" = usuń wszystkie; inny string = zastąp pierwszą lub dodaj
        if email is not None:
            if email == "":
                updated.mail_addresses = []
            else:
                mail_type = _MAIL_TYPE.get(email_type.lower(), "1")
                new_mail = ContactMailAddress(type=mail_type, custom_type="", address=email)
                if updated.mail_addresses:
                    updated.mail_addresses = [new_mail] + list(updated.mail_addresses[1:])
                else:
                    updated.mail_addresses = [new_mail]

        # Obsłuż phone: "" = usuń wszystkie; inny string = zastąp pierwszą lub dodaj
        if phone is not None:
            if phone == "":
                updated.phone_numbers = []
            else:
                ph_type = _PHONE_TYPE.get(phone_type.lower(), "2")
                new_phone = ContactPhoneNumber(type=ph_type, custom_type="", number=phone)
                if updated.phone_numbers:
                    updated.phone_numbers = [new_phone] + list(updated.phone_numbers[1:])
                else:
                    updated.phone_numbers = [new_phone]

        async def _update(client, session):
            _, group_key, _, key_version = await client.get_contact_group_info(session)
            await client.update_contact_api(session, updated, group_key, key_version)

        _, err = await _safe_call(sm, _update)
        if err:
            return err
        name = f"{updated.first_name} {updated.last_name}".strip() or updated.company
        logger.info("tuta_contacts_update: %r [%s, %s]", name, list_id[:12], elem_id[:12])
        return {
            "status": "updated",
            "list_id": list_id,
            "elem_id": elem_id,
            "name": name,
        }

    @mcp.tool()
    async def tuta_contacts_delete(
        list_id: str,
        elem_id: str,
    ) -> dict[str, Any]:
        """
        Permanently deletes a contact.

        Parameters:
        - list_id: Contact list ID.
        - elem_id: Contact element ID.
        """
        async def _delete(client, session):
            await client.delete_contact_api(session, list_id, elem_id)

        _, err = await _safe_call(sm, _delete)
        if err:
            return err
        logger.info("tuta_contacts_delete: [%s, %s]", list_id[:12], elem_id[:12])
        return {"status": "deleted", "list_id": list_id, "elem_id": elem_id}
