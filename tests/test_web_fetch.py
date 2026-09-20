"""Tests de web_fetch: validacion de URL y destilado con mocks (sin red)."""
import unittest
from unittest.mock import patch

from tools import execute_tool, load_tools_config, web_fetch

BIN = "/usr/bin/agent-browser"


class TestWebFetchValidation(unittest.TestCase):
    def test_rejects_non_url_input(self):
        self.assertIn("ERROR", web_fetch("gato"))

    def test_rejects_empty_input(self):
        self.assertIn("ERROR", web_fetch("   "))

    def test_rejects_non_http_scheme(self):
        self.assertIn("ERROR", web_fetch("ftp://example.com/file"))


class TestWebFetchBrowser(unittest.TestCase):
    @patch("tools.find_agent_browser", return_value=None)
    def test_browser_not_installed(self, _mock_bin):
        r = web_fetch("https://example.com")
        self.assertIn("agent-browser", r)

    @patch("tools._browser_get_text", return_value="")
    @patch("tools._run_browser", return_value="ok")
    @patch("tools.find_agent_browser", return_value=BIN)
    def test_empty_page_returns_error(self, _mock_bin, _mock_open, _mock_get):
        r = web_fetch("https://example.com")
        self.assertIn("ERROR", r)

    @patch("tools._browser_get_text", return_value="contenido de la pagina")
    @patch("tools._run_browser", return_value="ok")
    @patch("tools.find_agent_browser", return_value=BIN)
    def test_returns_distilled_text(self, _mock_bin, _mock_open, _mock_get):
        r = web_fetch("https://example.com")
        self.assertIn("https://example.com", r)
        self.assertIn("contenido de la pagina", r)

    @patch("tools._browser_get_text", return_value="x" * 5000)
    @patch("tools._run_browser", return_value="ok")
    @patch("tools.find_agent_browser", return_value=BIN)
    def test_truncates_to_max_output_chars(self, _mock_bin, _mock_open, _mock_get):
        r = web_fetch("https://example.com", max_output_chars=100)
        self.assertIn("truncated to 100 characters", r)
        self.assertLess(len(r), 5300)


class TestWebFetchDispatch(unittest.TestCase):
    @patch("tools._browser_get_text", return_value="contenido de la pagina")
    @patch("tools._run_browser", return_value="ok")
    @patch("tools.find_agent_browser", return_value=BIN)
    def test_execute_tool_web_fetch(self, _mock_bin, _mock_open, _mock_get):
        cfg = {"web_fetch": {"enabled": True, "timeout": 5, "max_output_chars": 3000}}
        r = execute_tool("web_fetch", "https://example.com", cfg)
        self.assertIn("contenido de la pagina", r)

    def test_disabled_tool_errors(self):
        cfg = {"web_fetch": {"enabled": False}}
        self.assertIn("ERROR", execute_tool("web_fetch", "https://example.com", cfg))

    def test_default_config_includes_web_fetch(self):
        cfg = load_tools_config("/nonexistent/tools.json")
        self.assertTrue(cfg["web_fetch"]["enabled"])


if __name__ == "__main__":
    unittest.main()
