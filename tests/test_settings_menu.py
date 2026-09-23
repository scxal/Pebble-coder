"""E2E del menu /settings: navegacion, toggle, edicion y guardado en config.json."""
import json
import unittest

from tests.helpers import CONFIG, KNOWN_CONFIG, AgentPty, ConfigGuard


def read_config():
    return json.loads(CONFIG.read_text())


class TestSettingsMenu(unittest.TestCase):
    def test_full_settings_flow(self):
        with ConfigGuard(KNOWN_CONFIG), AgentPty() as term:
            banner = term.read(2.0)
            with self.subTest("startup banner + prompt"):
                self.assertIn("Tú > ", banner)

            term.send(b"/settings\r")
            menu = term.read(1.2)
            with self.subTest("menu title"):
                self.assertIn("Configuración del agente", menu)
            with self.subTest("first row selected"):
                self.assertIn("❯  1. Idioma", menu)

            term.send(b"\x1b[B")  # down
            with self.subTest("down arrow selects item 2"):
                self.assertIn("❯  2. Modelo", term.read(0.8))

            term.send(b"\x1b[A")  # up
            with self.subTest("up arrow back to item 1"):
                self.assertIn("❯  1. Idioma", term.read(0.8))

            term.send(b"9")  # jump to Debug
            with self.subTest("number key selects item 9"):
                self.assertIn("❯  9. Debug", term.read(0.8))

            term.send(b"\r")  # toggle on
            term.read(0.8)
            with self.subTest("debug toggled on (file)"):
                self.assertEqual(read_config().get("debug"), "on")

            term.send(b"\r")  # toggle off
            term.read(0.8)
            with self.subTest("debug toggled off (file)"):
                self.assertEqual(read_config().get("debug"), "off")

            term.send(b"5\r")  # edit temperature
            with self.subTest("edit prompt shown"):
                self.assertIn("Nuevo valor para 'Temperatura'", term.read(0.8))

            term.send(b"abc\r")  # invalid
            term.read(0.8)
            with self.subTest("invalid number rejected (file unchanged)"):
                self.assertEqual(read_config().get("temperature"), 0.2)

            term.send(b"\r")  # edit again
            term.read(0.6)
            term.send(b"0.7\r")
            term.read(0.8)
            with self.subTest("valid temperature saved"):
                self.assertEqual(read_config().get("temperature"), 0.7)

            term.send(b"8\r")  # format -> xml
            term.read(0.8)
            with self.subTest("format cycled to xml"):
                self.assertEqual(read_config().get("format"), "xml")

            term.send(b"8\r")  # format -> text
            term.read(0.8)
            with self.subTest("format cycled back to text"):
                self.assertEqual(read_config().get("format"), "text")

            term.send(b"1\r")  # language -> en
            term.read(0.8)
            with self.subTest("language cycled to en (file)"):
                self.assertEqual(read_config().get("language"), "en")

            term.send(b"q")  # exit menu
            closed = term.read(0.8)
            with self.subTest("menu closed message (en applied live)"):
                self.assertIn("Menu closed.", closed)
            with self.subTest("prompt switched to English"):
                self.assertIn("You > ", closed)

            term.send(b"/foo\r")
            with self.subTest("unknown command lists all commands"):
                unk = term.read(0.8)
                self.assertIn("Unknown command: /foo", unk)
                self.assertIn("/settings, /tools, /exit, /quit", unk)

            term.send(b"/exit\r")
            with self.subTest("agent exits cleanly"):
                self.assertTrue(term.wait_exit())

    def test_config_guard_restores_original(self):
        original = CONFIG.read_bytes()
        with ConfigGuard({"debug": "on"}):
            self.assertNotEqual(CONFIG.read_bytes(), original)
        self.assertEqual(CONFIG.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
