"""
Test integracyjny tuta_mail_get_attachment.

Uruchamianie:
    TUTA_EMAIL=your@tuta.com TUTA_PASSWORD=... /usr/bin/python3.11 run.py tests/it_mail_attachment.py

Wymaga: co najmniej jednego maila z załącznikiem w INBOX konta testowego.
"""

import asyncio
import hashlib
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config
from tutamcp.session import SessionManager
from tutamcp.tools_mail import _sanitize_filename


async def run_tests() -> None:
    env = dict(os.environ)
    env.setdefault("TUTAMCP_ENABLE_MAIL", "1")
    env.setdefault("TUTAMCP_DOWNLOAD_DIR", "/tmp/tutamcp_test")
    cfg = load_config(env)
    sm = SessionManager(cfg)

    print("=== Test: tuta_mail_get_attachment ===\n")

    # znajdź mail z załącznikiem
    async def find_mail_with_attach(client, session):
        folders = await client.get_folders(session)
        inbox = next(f for f in folders if f.folder_type == "1")
        mails = await client.get_mails_in_folder(session, inbox.mail_list_id)
        mails.sort(key=lambda m: int(m.get("107", 0) or 0), reverse=True)
        for m in mails:
            if m.get("115"):
                mid = m.get("99", ["", ""])
                return mid[0] if isinstance(mid, list) else "", mid[1] if isinstance(mid, list) else str(mid)
        return None, None

    list_id, mail_id = await sm.call(find_mail_with_attach)
    if not mail_id:
        print("Brak maila z załącznikiem w INBOX — test pominięty")
        await sm.close()
        return

    print(f"Mail z załącznikiem: {mail_id[:8]}...")

    # pobierz załącznik indeks 0
    async def download_attach(client, session):
        mail_group_key = await client.get_mail_group_key(session)
        mail_raw = await client.get_single_mail(session, list_id, mail_id)
        attachments = await client.load_attachments(session, mail_raw, mail_group_key)
        return attachments[0]

    att = await sm.call(download_attach)
    print(f"Załącznik: name={att['name']!r} mime={att['mime_type']!r} size={len(att['data'])} B")
    md5 = hashlib.md5(att["data"]).hexdigest()
    print(f"MD5: {md5}")
    assert len(att["data"]) > 0, "Puste dane załącznika"

    # test sanityzacji nazwy pliku
    dangerous_names = [
        ("../etc/passwd", "..etc.passwd"),
        ("../../root/.ssh/id_rsa", "..root..ssh.id_rsa"),
        ("file with spaces.pdf", "file with spaces.pdf"),
        ("normal_file.txt", "normal_file.txt"),
        ("../file.txt", "..file.txt"),
    ]
    print("\n=== Test sanityzacji nazwy pliku ===")
    for raw, expected_safe in dangerous_names:
        result = _sanitize_filename(raw)
        # weryfikuj brak .. i /
        assert ".." not in result.split(os.sep), f"Path traversal w: {result!r}"
        assert "/" not in result, f"Slash w: {result!r}"
        print(f"  {raw!r:35} → {result!r}")

    # zapisz plik do katalogu download
    os.makedirs(cfg.download_dir, exist_ok=True)
    filename = _sanitize_filename(att["name"] or "attachment")
    local_path = os.path.join(cfg.download_dir, filename)
    with open(local_path, "wb") as f:
        f.write(att["data"])

    size_on_disk = os.path.getsize(local_path)
    md5_on_disk = hashlib.md5(open(local_path, "rb").read()).hexdigest()
    print(f"\nZapisano: {local_path}")
    print(f"Rozmiar: {size_on_disk} B, MD5: {md5_on_disk}")
    assert size_on_disk == len(att["data"]), "Rozmiar na dysku != rozmiar danych"
    assert md5_on_disk == md5, "MD5 na dysku != MD5 danych"
    print("  OK: rozmiar i MD5 zgodne")

    await sm.close()
    print("\n=== Wszystkie testy PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
