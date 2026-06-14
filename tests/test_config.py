"""
Testy jednostkowe config.py — bez sieci, bez pliku credentials.
Uruchamianie: /usr/bin/python3.11 run.py tests/test_config.py
"""

import os
import sys
import tempfile
import unittest

# dodaj katalog repo do ścieżki (na wypadek uruchomienia bezpośrednio)
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import Config, ConfigError, MailMode, MailSend, load_config


def _base_env(**overrides) -> dict:
    """Minimalne środowisko z włączoną pocztą."""
    env = {
        "TUTAMCP_ENABLE_MAIL": "1",
        "TUTA_EMAIL": "test@example.com",
        "TUTA_PASSWORD": "sekret",
        "TUTAMCP_OWNER_EMAIL": "owner@example.com",
    }
    env.update(overrides)
    return env


class TestModuleToggles(unittest.TestCase):
    def test_all_disabled_no_credentials_ok(self):
        # żaden moduł nie wymaga e-mail/hasła
        cfg = load_config({})
        self.assertFalse(cfg.enable_mail)
        self.assertFalse(cfg.enable_calendar)
        self.assertIsNone(cfg.email)

    def test_enable_mail_requires_email(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config({"TUTAMCP_ENABLE_MAIL": "1", "TUTA_PASSWORD": "x"})
        self.assertIn("TUTA_EMAIL", str(ctx.exception))

    def test_enable_mail_requires_password(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config({"TUTAMCP_ENABLE_MAIL": "1", "TUTA_EMAIL": "a@b.com"})
        self.assertIn("TUTA_PASSWORD", str(ctx.exception))

    def test_any_module_triggers_credential_check(self):
        for var in ("TUTAMCP_ENABLE_CALENDAR", "TUTAMCP_ENABLE_CONTACTS", "TUTAMCP_ENABLE_DRIVE"):
            with self.assertRaises(ConfigError):
                load_config({var: "1"})


class TestMailMode(unittest.TestCase):
    def test_default_mode_dedicated(self):
        cfg = load_config(_base_env())
        self.assertEqual(cfg.mail_mode, MailMode.DEDICATED)

    def test_shared_mode(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="shared"))
        self.assertEqual(cfg.mail_mode, MailMode.SHARED)

    def test_invalid_mode(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_base_env(TUTAMCP_MAIL_MODE="supermode"))
        self.assertIn("TUTAMCP_MAIL_MODE", str(ctx.exception))

    def test_folder_mode_requires_folder_name(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_base_env(TUTAMCP_MAIL_MODE="folder"))
        self.assertIn("TUTAMCP_MAIL_FOLDER", str(ctx.exception))

    def test_folder_mode_with_folder_name(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="folder", TUTAMCP_MAIL_FOLDER="Claude"))
        self.assertEqual(cfg.mail_mode, MailMode.FOLDER)
        self.assertEqual(cfg.mail_folder, "Claude")


class TestMailSendPolicy(unittest.TestCase):
    def test_dedicated_default_full(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="dedicated"))
        self.assertEqual(cfg.mail_send, MailSend.FULL)

    def test_shared_default_reply_only(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="shared"))
        self.assertEqual(cfg.mail_send, MailSend.REPLY_ONLY)

    def test_folder_default_reply_only(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="folder", TUTAMCP_MAIL_FOLDER="Claude"))
        self.assertEqual(cfg.mail_send, MailSend.REPLY_ONLY)

    def test_dedicated_explicit_reply_only(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="dedicated", TUTAMCP_MAIL_SEND="reply_only"))
        self.assertEqual(cfg.mail_send, MailSend.REPLY_ONLY)

    def test_shared_explicit_full(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_MODE="shared", TUTAMCP_MAIL_SEND="full"))
        self.assertEqual(cfg.mail_send, MailSend.FULL)

    def test_folder_full_is_error(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_base_env(
                TUTAMCP_MAIL_MODE="folder",
                TUTAMCP_MAIL_FOLDER="Claude",
                TUTAMCP_MAIL_SEND="full",
            ))
        self.assertIn("reply_only", str(ctx.exception))

    def test_invalid_send_policy(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(_base_env(TUTAMCP_MAIL_SEND="broadcast"))
        self.assertIn("TUTAMCP_MAIL_SEND", str(ctx.exception))


class TestWhitelist(unittest.TestCase):
    def test_owner_always_in_whitelist(self):
        cfg = load_config(_base_env(TUTAMCP_OWNER_EMAIL="boss@example.com"))
        self.assertIn("boss@example.com", cfg.command_whitelist)

    def test_csv_whitelist_parsed(self):
        cfg = load_config(_base_env(
            TUTAMCP_COMMAND_WHITELIST="alice@x.com,BOB@X.COM",
            TUTAMCP_OWNER_EMAIL="owner@x.com",
        ))
        self.assertIn("alice@x.com", cfg.command_whitelist)
        self.assertIn("bob@x.com", cfg.command_whitelist)  # normalizacja lowercase
        self.assertIn("owner@x.com", cfg.command_whitelist)

    def test_owner_not_duplicated_in_whitelist(self):
        cfg = load_config(_base_env(
            TUTAMCP_COMMAND_WHITELIST="owner@example.com",
            TUTAMCP_OWNER_EMAIL="owner@example.com",
        ))
        self.assertEqual(cfg.command_whitelist.count("owner@example.com"), 1)

    def test_empty_whitelist_only_owner(self):
        cfg = load_config(_base_env(TUTAMCP_OWNER_EMAIL="only@x.com"))
        self.assertEqual(cfg.command_whitelist, ["only@x.com"])


class TestCredentialsFile(unittest.TestCase):
    def test_missing_credentials_file_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config({
                "TUTAMCP_CREDENTIALS_FILE": "/nonexistent/path/creds.env",
                "TUTAMCP_ENABLE_MAIL": "1",
            })
        self.assertIn("/nonexistent/path/creds.env", str(ctx.exception))

    def test_credentials_file_loaded(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("TUTA_EMAIL=file@example.com\n")
            f.write("TUTA_PASSWORD=filepass\n")
            path = f.name
        try:
            cfg = load_config({
                "TUTAMCP_CREDENTIALS_FILE": path,
                "TUTAMCP_ENABLE_MAIL": "1",
                "TUTAMCP_OWNER_EMAIL": "owner@x.com",
            })
            self.assertEqual(cfg.email, "file@example.com")
            self.assertEqual(cfg.password, "filepass")
        finally:
            os.unlink(path)

    def test_credentials_file_overrides_env(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("TUTA_EMAIL=fromfile@example.com\n")
            f.write("TUTA_PASSWORD=fromfile\n")
            path = f.name
        try:
            cfg = load_config({
                "TUTAMCP_CREDENTIALS_FILE": path,
                "TUTA_EMAIL": "fromenv@example.com",
                "TUTA_PASSWORD": "fromenv",
                "TUTAMCP_ENABLE_MAIL": "1",
                "TUTAMCP_OWNER_EMAIL": "owner@x.com",
            })
            self.assertEqual(cfg.email, "fromfile@example.com")
            self.assertEqual(cfg.password, "fromfile")
        finally:
            os.unlink(path)

    def test_credentials_file_comments_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# komentarz\n")
            f.write("TUTA_EMAIL=ok@example.com\n")
            f.write("  \n")
            f.write("TUTA_PASSWORD=ok\n")
            path = f.name
        try:
            cfg = load_config({
                "TUTAMCP_CREDENTIALS_FILE": path,
                "TUTAMCP_ENABLE_MAIL": "1",
                "TUTAMCP_OWNER_EMAIL": "o@x.com",
            })
            self.assertEqual(cfg.email, "ok@example.com")
        finally:
            os.unlink(path)


class TestDefaults(unittest.TestCase):
    def test_defaults_no_modules(self):
        cfg = load_config({})
        self.assertEqual(cfg.download_dir, "/tmp/tutamcp")
        self.assertEqual(cfg.log_level, "INFO")
        self.assertIsNone(cfg.log_file)
        self.assertEqual(cfg.mail_mode, MailMode.DEDICATED)
        self.assertFalse(cfg.cc_owner)

    def test_cc_owner_flag(self):
        cfg = load_config(_base_env(TUTAMCP_MAIL_CC_OWNER="1"))
        self.assertTrue(cfg.cc_owner)

    def test_log_level_uppercase(self):
        cfg = load_config(_base_env(LOG_LEVEL="debug"))
        self.assertEqual(cfg.log_level, "DEBUG")


if __name__ == "__main__":
    # unittest.main() nie wykrywa klas przez exec() — ładujemy suite ręcznie
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestModuleToggles,
        TestMailMode,
        TestMailSendPolicy,
        TestWhitelist,
        TestCredentialsFile,
        TestDefaults,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
