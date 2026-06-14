"""
Testy jednostkowe dla policy.py — bez dostępu do sieci.

Uruchamianie:
    /usr/bin/python3.11 run.py tests/test_policy.py
"""

import sys
import os
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tutamcp.config import load_config, MailMode, MailSend
from tutamcp.policy import allowed_tools, check_folder_access


def make_cfg(mode: str, mail_send: str = "", mail_folder: str = "") -> object:
    """Pomocnicza: tworzy Config z minimalnymi polami."""
    env = {
        "TUTA_EMAIL": "test@example.com",
        "TUTA_PASSWORD": "secret",
        "TUTAMCP_ENABLE_MAIL": "1",
        "TUTAMCP_MAIL_MODE": mode,
    }
    if mail_send:
        env["TUTAMCP_MAIL_SEND"] = mail_send
    if mail_folder:
        env["TUTAMCP_MAIL_FOLDER"] = mail_folder
    return load_config(env)


class TestAllowedToolsDedicated(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg("dedicated")  # domyślnie FULL

    def test_read_tools_present(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_list_folders", "tuta_mail_list", "tuta_mail_read",
                  "tuta_mail_get_attachment"]:
            self.assertIn(t, tools, f"Brak narzędzia {t} w dedicated")

    def test_action_tools_present(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_reply", "tuta_mail_move", "tuta_mail_delete", "tuta_mail_mark"]:
            self.assertIn(t, tools)

    def test_send_full_in_dedicated(self):
        tools = allowed_tools(self.cfg)
        self.assertIn("tuta_mail_send", tools)

    def test_folder_crud_in_dedicated(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_folder_create", "tuta_mail_folder_rename", "tuta_mail_folder_delete"]:
            self.assertIn(t, tools)

    def test_dedicated_reply_only(self):
        cfg = make_cfg("dedicated", mail_send="reply_only")
        tools = allowed_tools(cfg)
        self.assertNotIn("tuta_mail_send", tools)
        self.assertIn("tuta_mail_reply", tools)


class TestAllowedToolsShared(unittest.TestCase):

    def test_shared_defaults_reply_only(self):
        cfg = make_cfg("shared")  # domyślnie REPLY_ONLY dla shared
        tools = allowed_tools(cfg)
        self.assertNotIn("tuta_mail_send", tools)
        self.assertIn("tuta_mail_reply", tools)

    def test_shared_full_explicit(self):
        cfg = make_cfg("shared", mail_send="full")
        tools = allowed_tools(cfg)
        self.assertIn("tuta_mail_send", tools)

    def test_shared_has_folder_crud(self):
        cfg = make_cfg("shared")
        tools = allowed_tools(cfg)
        for t in ["tuta_mail_folder_create", "tuta_mail_folder_rename", "tuta_mail_folder_delete"]:
            self.assertIn(t, tools)


class TestAllowedToolsFolder(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg("folder", mail_folder="test_mail_list_id")

    def test_read_tools_present(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_list_folders", "tuta_mail_list", "tuta_mail_read",
                  "tuta_mail_get_attachment"]:
            self.assertIn(t, tools)

    def test_no_send_in_folder_mode(self):
        tools = allowed_tools(self.cfg)
        self.assertNotIn("tuta_mail_send", tools)

    def test_reply_available_in_folder_mode(self):
        tools = allowed_tools(self.cfg)
        self.assertIn("tuta_mail_reply", tools)

    def test_no_folder_crud_in_folder_mode(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_folder_create", "tuta_mail_folder_rename", "tuta_mail_folder_delete"]:
            self.assertNotIn(t, tools, f"Narzędzie {t} NIE powinno być dostępne w trybie folder")

    def test_action_tools_in_folder_mode(self):
        tools = allowed_tools(self.cfg)
        for t in ["tuta_mail_move", "tuta_mail_delete", "tuta_mail_mark"]:
            self.assertIn(t, tools)


class TestAllowedToolsMailDisabled(unittest.TestCase):

    def test_no_tools_when_mail_disabled(self):
        env = {
            "TUTA_EMAIL": "test@example.com",
            "TUTA_PASSWORD": "secret",
            "TUTAMCP_ENABLE_MAIL": "0",
        }
        cfg = load_config(env)
        self.assertEqual(allowed_tools(cfg), set())


class TestCheckFolderAccess(unittest.TestCase):

    def test_dedicated_always_true(self):
        cfg = make_cfg("dedicated")
        self.assertTrue(check_folder_access(cfg, "any_id"))
        self.assertTrue(check_folder_access(cfg, ""))
        self.assertTrue(check_folder_access(cfg, "different_id"))

    def test_shared_always_true(self):
        cfg = make_cfg("shared")
        self.assertTrue(check_folder_access(cfg, "any_id"))

    def test_folder_mode_matches(self):
        cfg = make_cfg("folder", mail_folder="my_folder_id")
        self.assertTrue(check_folder_access(cfg, "my_folder_id"))

    def test_folder_mode_mismatch(self):
        cfg = make_cfg("folder", mail_folder="my_folder_id")
        self.assertFalse(check_folder_access(cfg, "other_folder_id"))
        self.assertFalse(check_folder_access(cfg, ""))

    def test_folder_mode_no_folder_configured(self):
        # folder mode bez TUTAMCP_MAIL_FOLDER — błąd walidacji config
        # (config.py go odrzuci, więc ten case jest teoretyczny)
        # Weryfikujemy że check_folder_access zwraca False gdy brak konfiguracji
        # Tworzymy "ręcznie" bo load_config by odrzucił
        from tutamcp.config import Config, MailMode, MailSend
        cfg = Config(
            enable_mail=True,
            enable_calendar=False,
            enable_contacts=False,
            enable_drive=False,
            mail_mode=MailMode.FOLDER,
            mail_folder=None,
            mail_send=MailSend.REPLY_ONLY,
            owner_email="owner@example.com",
            command_whitelist=["owner@example.com"],
            cc_owner=False,
            email="test@example.com",
            password="secret",
            download_dir="/tmp",
            tutaproxy_path="",
            log_level="INFO",
            log_file=None,
        )
        self.assertFalse(check_folder_access(cfg, "some_id"))


class TestTrustRequireE2E(unittest.TestCase):
    """Testy TUTAMCP_TRUST_REQUIRE_E2E."""

    def test_default_require_e2e_true(self):
        cfg = make_cfg("dedicated")
        self.assertTrue(cfg.trust_require_e2e)

    def test_explicit_require_e2e_false(self):
        env = {
            "TUTA_EMAIL": "t@e.com", "TUTA_PASSWORD": "s",
            "TUTAMCP_ENABLE_MAIL": "1",
            "TUTAMCP_MAIL_MODE": "dedicated",
            "TUTAMCP_TRUST_REQUIRE_E2E": "0",
        }
        cfg = load_config(env)
        self.assertFalse(cfg.trust_require_e2e)

    def test_explicit_require_e2e_true(self):
        env = {
            "TUTA_EMAIL": "t@e.com", "TUTA_PASSWORD": "s",
            "TUTAMCP_ENABLE_MAIL": "1",
            "TUTAMCP_MAIL_MODE": "dedicated",
            "TUTAMCP_TRUST_REQUIRE_E2E": "1",
        }
        cfg = load_config(env)
        self.assertTrue(cfg.trust_require_e2e)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestAllowedToolsDedicated,
        TestAllowedToolsShared,
        TestAllowedToolsFolder,
        TestAllowedToolsMailDisabled,
        TestCheckFolderAccess,
        TestTrustRequireE2E,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
