"""Tests del tema central de color: seleccion, degradacion y fila de /settings."""
import json
import os
import sys
import unittest
from unittest.mock import patch

import agent
import theme
from tests.helpers import CONFIG, AgentPty, ConfigGuard


class TestThemeSelection(unittest.TestCase):
    def tearDown(self):
        theme.set_theme("default")

    def test_default_and_available(self):
        self.assertEqual(theme.DEFAULT_THEME, "default")
        self.assertEqual(theme.available_themes(), ["default", "light", "mono"])

    def test_unknown_theme_is_ignored(self):
        theme.set_theme("light")
        self.assertEqual(theme.set_theme("nope"), "light")
        self.assertEqual(theme.current_theme(), "light")

    def test_c_with_empty_code_is_plain(self):
        self.assertEqual(theme.c("x", ""), "x")


class TestThemeRendering(unittest.TestCase):
    def tearDown(self):
        theme.set_theme("default")

    def _tty(self):
        return patch.object(sys.stdout, "isatty", return_value=True)

    def test_default_keeps_256_codes(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color", "COLORTERM": ""}, clear=False), self._tty():
            theme.set_theme("default")
            self.assertEqual(theme.green("x"), "\x1b[38;5;40mx\x1b[0m")
            self.assertEqual(theme.blue("x"), "\x1b[48;5;21;38;5;231mx\x1b[0m")
            self.assertEqual(theme.dim("x"), "\x1b[90mx\x1b[0m")

    def test_16_color_terminal_degrades_256(self):
        with patch.dict(os.environ, {"TERM": "xterm", "COLORTERM": ""}, clear=False), self._tty():
            theme.set_theme("default")
            self.assertEqual(theme.green("x"), "\x1b[32mx\x1b[0m")
            self.assertEqual(theme.blue("x"), "\x1b[44;37mx\x1b[0m")
            self.assertEqual(theme.cyan("x"), "\x1b[36mx\x1b[0m")

    def test_dumb_terminal_drops_color_keeps_attributes(self):
        with patch.dict(os.environ, {"TERM": "dumb"}, clear=False), self._tty():
            theme.set_theme("default")
            self.assertEqual(theme.green("x"), "x")
            self.assertEqual(theme.dim("x"), "x")
            self.assertEqual(theme.bold("x"), "\x1b[1mx\x1b[0m")
            self.assertEqual(theme.reverse("x"), "\x1b[7mx\x1b[0m")

    def test_no_color_env_drops_color(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color", "NO_COLOR": "1"}, clear=False), self._tty():
            theme.set_theme("default")
            self.assertEqual(theme.green("x"), "x")

    def test_mono_theme_is_plain(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False), self._tty():
            theme.set_theme("mono")
            self.assertEqual(theme.green("x"), "x")
            self.assertEqual(theme.blue("x"), "x")
            self.assertEqual(theme.bold("x"), "\x1b[1mx\x1b[0m")

    def test_light_theme_uses_basic_colors(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False), self._tty():
            theme.set_theme("light")
            self.assertEqual(theme.green("x"), "\x1b[32mx\x1b[0m")
            self.assertEqual(theme.dim("x"), "\x1b[2mx\x1b[0m")


class TestThemeSettingsRow(unittest.TestCase):
    def tearDown(self):
        theme.set_theme("default")

    def test_settings_has_theme_choice_row(self):
        items = agent.build_settings_items({"theme": "light"})
        labels = [item.label for item in items]
        self.assertIn(agent.t("label_theme"), labels)
        row = items[labels.index(agent.t("label_theme"))]
        self.assertEqual(row.kind, "choice")
        self.assertEqual(row.choices, theme.available_themes())

    def test_theme_row_applies_live_and_saves(self):
        with ConfigGuard({"theme": "default"}):
            cfg = json.loads(CONFIG.read_text())
            items = agent.build_settings_items(cfg)
            row = next(item for item in items if item.label == agent.t("label_theme"))
            self.assertEqual(theme.current_theme(), "default")
            row.on_change("mono")
            with self.subTest("aplicado en caliente"):
                self.assertEqual(theme.current_theme(), "mono")
            with self.subTest("persistido en config.json"):
                self.assertEqual(json.loads(CONFIG.read_text())["theme"], "mono")


class TestThemeE2E(unittest.TestCase):
    def test_default_theme_paints_the_bar(self):
        with ConfigGuard({"theme": "default", "language": "es", "stats": "on"}), AgentPty() as term:
            out = term.read(2.0)
            self.assertIn("\x1b[90m", out)
            term.send(b"/exit\r")
            self.assertTrue(term.wait_exit())

    def test_mono_theme_removes_color_from_ui(self):
        with ConfigGuard({"theme": "mono", "language": "es", "stats": "on"}), AgentPty() as term:
            out = term.read(2.0)
            self.assertNotIn("\x1b[90m", out)
            self.assertNotIn("38;5;", out)
            term.send(b"/exit\r")
            self.assertTrue(term.wait_exit())

    def test_settings_theme_row_cycles_and_saves(self):
        with ConfigGuard({"theme": "default", "language": "es"}), AgentPty() as term:
            term.read(2.0)
            term.send(b"/settings\r")
            menu = term.read(1.2)
            with self.subTest("fila Tema visible"):
                self.assertIn(agent.t("label_theme"), menu)
            for _ in range(18):
                term.send(b"\x1b[B")  # bajar hasta la ultima fila (Tema)
            term.read(0.8)
            term.send(b"\r")  # default -> light
            term.read(0.8)
            with self.subTest("tema ciclado y guardado"):
                self.assertEqual(json.loads(CONFIG.read_text())["theme"], "light")
            term.send(b"q")
            term.read(0.5)
            term.send(b"/exit\r")
            self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
