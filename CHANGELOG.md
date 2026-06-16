# Changelog

## v0.1.4 (2026-06-16)

- Fixed `tuta_mail_list`: added `unread` parameter (`bool|None`) to filter emails by read status — enables idempotent autonomous polling (`unread=True` skips already-processed emails)

## v0.1.3 (2026-06-15)

- Added `external_password` parameter to `tuta_mail_send` for Secure External delivery — recipients get a link and enter the password to read the email
- Removed hardcoded `TUTAPROXY_PATH` fallback — path must be set explicitly in MCP config

## v0.1.2 (2026-06-13)

- Fixed `tuta_mail_move` to custom (user-created) folders — requires tutaproxy ≥ 1.3.10
- Added `tuta_mail_list_labels` and `tuta_mail_apply_labels`

## v0.1.1 (2026-06-13)

- Added Dockerfile for dependency-free distribution via Docker
- All 4 modules complete: mail, calendar, contacts, drive
- Structured error handling: `TutaAPIError` converted to readable tool results instead of exceptions
- Security: path traversal blocked on attachment/drive downloads; credentials file permission check; stdout kept clean
- Drive: graceful degradation on free Tuta accounts (HTTP 412 → informative error)

## v0.1.0 (2026-06-13)

- Initial release
- Mail: list folders/emails, read, send, reply, move, delete, mark, folder CRUD, labels
- Calendar: list events, create/update/delete (RRULE supported)
- Contacts: list/search, get, create, update, delete
- Drive: list, download, upload, mkdir, rename, move, delete (path-based navigation)
- Trust model: `trusted_sender` and `e2e` annotations on every message; `only_trusted` filter on list; E2E detection via TutaCrypt field 1310
- Mail modes: `dedicated` / `shared` / `folder`; send policy: `reply_only` / `full`
- Tool registration is conditional: disabled modules register no tools
