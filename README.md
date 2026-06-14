# tutamcp

MCP server giving Claude access to a [Tuta](https://tuta.com) account: mail, calendar, contacts, and drive. Each module is enabled independently. Built on top of [tutaproxy](https://github.com/peix2/tutaproxy-public)'s `TutaClient` — no direct Tuta API calls.

**30 MCP tools** across 4 modules. Requires [tutaproxy-public](https://github.com/peix2/tutaproxy-public) ≥ v1.3.10.

## Quickstart — Docker

The easiest setup: no local dependencies beyond Docker. The image bundles tutaproxy at build time.

```bash
git clone https://github.com/peix2/tutamcp-public.git
cd tutamcp-public
docker build -t tutamcp .
```

Pin a specific tutaproxy release (default: `v1.3.10`):

```bash
docker build --build-arg TUTAPROXY_REF=v1.3.10 -t tutamcp .
```

Create a credentials file (`chmod 600`):

```
TUTA_EMAIL=your@tuta.com
TUTA_PASSWORD=yourpassword
```

Register in Claude Code (`.mcp.json` or `~/.claude.json`):

```json
{
  "mcpServers": {
    "tutamcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/credentials.env:/creds.env:ro",
        "-e", "TUTAMCP_CREDENTIALS_FILE=/creds.env",
        "-e", "TUTAMCP_ENABLE_MAIL=1",
        "-e", "TUTAMCP_MAIL_MODE=dedicated",
        "-e", "TUTAMCP_OWNER_EMAIL=you@tuta.com",
        "tutamcp"
      ]
    }
  }
}
```

## Without Docker

Requires Python 3.11 and a local clone of [tutaproxy-public](https://github.com/peix2/tutaproxy-public).

```bash
git clone https://github.com/peix2/tutamcp-public.git
cd tutamcp-public
pip install --target=.venv/lib/python3.11/site-packages -r requirements.txt
```

Register in Claude Code:

```json
{
  "mcpServers": {
    "tutamcp": {
      "command": "python3.11",
      "args": ["/path/to/tutamcp-public/run.py", "/path/to/tutamcp-public/server.py"],
      "env": {
        "TUTAPROXY_PATH": "/path/to/tutaproxy-public",
        "TUTAMCP_CREDENTIALS_FILE": "/path/to/credentials.env",
        "TUTAMCP_ENABLE_MAIL": "1",
        "TUTAMCP_MAIL_MODE": "dedicated",
        "TUTAMCP_OWNER_EMAIL": "you@tuta.com",
        "TUTAMCP_DOWNLOAD_DIR": "/tmp/tutamcp"
      }
    }
  }
}
```

For Claude Desktop, use the same block in `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

## Configuration

See [`config.example.env`](config.example.env) for all variables. Key options:

### Mail modes

| Mode | Description |
|---|---|
| `dedicated` | Account belongs to Claude only. Full access, send enabled by default. |
| `shared` | Account shared with the user. Full read/write access; send policy controlled by `TUTAMCP_MAIL_SEND`. |
| `folder` | Shared account; Claude sees only the folder set in `TUTAMCP_MAIL_FOLDER`. Send is always reply-only. |

### Send policy

`TUTAMCP_MAIL_SEND=reply_only` — only `tuta_mail_reply` is registered; recipients are derived from the original mail only, no arbitrary addresses accepted.

`TUTAMCP_MAIL_SEND=full` — also registers `tuta_mail_send` for initiating new threads.

Default: `dedicated` → `full`, `shared` → `reply_only`, `folder` → always `reply_only`.

### Trusted senders

Used for autonomous mail handling (e.g. a background poller that wakes Claude to process incoming commands).

| Variable | Description |
|---|---|
| `TUTAMCP_OWNER_EMAIL` | Always trusted. |
| `TUTAMCP_COMMAND_WHITELIST` | Comma-separated list of additional trusted addresses. |
| `TUTAMCP_TRUST_REQUIRE_E2E` | `1` (default) — trust requires end-to-end encryption (Tuta→Tuta, TutaCrypt). Protects against spoofed `From` headers on external mail; owner and whitelist must use Tuta accounts. Set to `0` to trust by address alone. |
| `TUTAMCP_MAIL_CC_OWNER` | `1` — automatically CC the owner on every outgoing mail. |

`tuta_mail_list` and `tuta_mail_read` return `trusted_sender: bool` and `e2e: bool` on every message. Pass `only_trusted=True` to `tuta_mail_list` to filter to trusted senders only.

## Tools

### Status

| Tool | Description |
|---|---|
| `tuta_status` | Server info: version, enabled modules, mail mode/send policy, session state |

### Mail

| Tool | Description |
|---|---|
| `tuta_mail_list_folders` | List all folders |
| `tuta_mail_list` | List emails without body. Supports `only_trusted`, `unread`, pagination |
| `tuta_mail_read` | Read full email with decrypted body and attachment metadata |
| `tuta_mail_get_attachment` | Download attachment to `TUTAMCP_DOWNLOAD_DIR` |
| `tuta_mail_send` | Send new email (requires `mail_send=full`) |
| `tuta_mail_reply` | Reply to email; recipients derived from original only |
| `tuta_mail_move` | Move to folder |
| `tuta_mail_delete` | Delete permanently or move to trash |
| `tuta_mail_mark` | Mark as read/unread |
| `tuta_mail_folder_create` | Create custom folder |
| `tuta_mail_folder_rename` | Rename custom folder |
| `tuta_mail_folder_delete` | Delete custom folder |
| `tuta_mail_list_labels` | List labels |
| `tuta_mail_apply_labels` | Add/remove labels on a mail |

### Calendar

| Tool | Description |
|---|---|
| `tuta_calendar_list_events` | List events in a date range (recurring events always included) |
| `tuta_calendar_create_event` | Create event with optional RRULE recurrence |
| `tuta_calendar_update_event` | Update event |
| `tuta_calendar_delete_event` | Delete event |

Note: editing a single occurrence of a recurring series is not supported.

### Contacts

| Tool | Description |
|---|---|
| `tuta_contacts_list` | List/search contacts by name, company, or email |
| `tuta_contacts_get` | Get full contact details |
| `tuta_contacts_create` | Create contact |
| `tuta_contacts_update` | Update contact fields |
| `tuta_contacts_delete` | Delete contact |

### Drive

| Tool | Description |
|---|---|
| `tuta_drive_list` | List folder contents by path |
| `tuta_drive_download` | Download file to `TUTAMCP_DOWNLOAD_DIR` |
| `tuta_drive_upload` | Upload local file |
| `tuta_drive_mkdir` | Create folder |
| `tuta_drive_rename` | Rename file or folder |
| `tuta_drive_move` | Move file or folder |
| `tuta_drive_delete` | Delete file or folder |

Drive requires a paid Tuta account. Free accounts receive an informative error rather than a crash.

## Security

- Credentials are never logged. The server warns if the credentials file permissions are wider than `600`.
- All logging goes to `stderr` or a log file. `stdout` is reserved for the MCP protocol.
- Tool registration is conditional: a disabled module registers no tools — Claude doesn't see them at all.
- In `folder` mode, all operations are scoped to the configured folder; attempts to access outside it are rejected at the tool level.
- Reply-only policy is enforced structurally: `tuta_mail_send` is simply not registered, not blocked at runtime.
- Path traversal on attachment/drive downloads is blocked (basename sanitization + regex).

## License

AGPL-3.0 — see [LICENSE](LICENSE).
