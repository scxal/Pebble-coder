"""Unit tests de helpers puros: argumentos de write_file, validators, MenuItem."""
import unittest

import agent
from menu import MenuItem, render_row
from tools import parse_write_file_args


class TestParseWriteFileArgs(unittest.TestCase):
    def test_json_format(self):
        self.assertEqual(parse_write_file_args('{"path": "a.txt", "content": "hola"}'), ("a.txt", "hola"))

    def test_multiline_format(self):
        self.assertEqual(parse_write_file_args("notas.md\nlinea1\nlinea2"), ("notas.md", "linea1\nlinea2"))

    def test_multiline_with_path_prefix(self):
        self.assertEqual(parse_write_file_args("path: a.txt\ncontenido"), ("a.txt", "contenido"))

    def test_key_value_format(self):
        self.assertEqual(parse_write_file_args('path="a.txt", content="hola"'), ("a.txt", "hola"))

    def test_comma_format(self):
        self.assertEqual(parse_write_file_args("a.txt, hola"), ("a.txt", "hola"))

    def test_plain_path(self):
        self.assertEqual(parse_write_file_args("solo/ruta.txt"), ("solo/ruta.txt", ""))


class TestAgentValidators(unittest.TestCase):
    def test_temperature_valid(self):
        self.assertEqual(agent._validate_temperature("0.5"), 0.5)
        self.assertEqual(agent._validate_temperature("0"), 0.0)
        self.assertEqual(agent._validate_temperature("2"), 2.0)

    def test_temperature_invalid(self):
        with self.assertRaises(ValueError):
            agent._validate_temperature("abc")
        with self.assertRaises(ValueError):
            agent._validate_temperature("2.5")

    def test_positive_int_valid(self):
        self.assertEqual(agent._validate_positive_int("5"), 5)
        self.assertEqual(agent._validate_positive_int("1"), 1)

    def test_positive_int_invalid(self):
        for bad in ("0", "-3", "x", "1.5"):
            with self.assertRaises(ValueError):
                agent._validate_positive_int(bad)


class TestIsEnabled(unittest.TestCase):
    def test_truthy_values(self):
        for v in ("on", "true", "yes", "1", True):
            self.assertTrue(agent.is_enabled({"k": v}, "k"), v)

    def test_falsy_values(self):
        for v in ("off", "false", "no", "0", "", False):
            self.assertFalse(agent.is_enabled({"k": v}, "k"), v)

    def test_missing_key_uses_default(self):
        self.assertFalse(agent.is_enabled({}, "k"))
        self.assertTrue(agent.is_enabled({}, "k", True))


class TestMenuItem(unittest.TestCase):
    def test_toggle_flip(self):
        item = MenuItem("d", "toggle", value="off")
        self.assertEqual(item.flip(), "on")
        self.assertEqual(item.flip(), "off")

    def test_toggle_accepts_bool_like(self):
        item = MenuItem("d", "toggle", value=True)
        self.assertEqual(item.flip(), "off")

    def test_choice_cycles_and_wraps(self):
        item = MenuItem("f", "choice", value="text", choices=["text", "xml"])
        self.assertEqual(item.cycle(), "xml")
        self.assertEqual(item.cycle(), "text")

    def test_choice_with_unknown_value_starts_fresh(self):
        item = MenuItem("f", "choice", value="weird", choices=["text", "xml"])
        self.assertEqual(item.cycle(), "text")

    def test_render_action_has_no_value(self):
        item = MenuItem("Sí", "action")
        self.assertNotIn("None", render_row(item, False, 1))

    def test_render_toggle_colored_and_plain(self):
        item = MenuItem("d", "toggle", value="on")
        self.assertIn("on", item.value_text(plain=True))
        self.assertIn("[on]", item.value_text())


class TestToolJsonArgs(unittest.TestCase):
    def test_json_path_for_read_file(self):
        from tools import _coerce_json_args
        self.assertEqual(_coerce_json_args('{"path": "a.txt"}', "read_file"), "a.txt")

    def test_json_command_for_run_command(self):
        from tools import _coerce_json_args
        self.assertEqual(_coerce_json_args('{"command": "ls -la"}', "run_command"), "ls -la")

    def test_json_url_for_web_fetch(self):
        from tools import _coerce_json_args
        self.assertEqual(_coerce_json_args('{"url": "https://example.com"}', "web_fetch"),
                         "https://example.com")

    def test_single_key_fallback(self):
        from tools import _coerce_json_args
        self.assertEqual(_coerce_json_args('{"whatever": "value"}', "read_file"), "value")

    def test_write_file_passthrough(self):
        from tools import _normalize_tool_input
        raw = '{"path": "a.txt", "content": "hola"}'
        self.assertEqual(_normalize_tool_input(raw, "write_file"), raw)

    def test_execute_read_file_with_json_args(self):
        import tempfile
        from pathlib import Path
        from tools import execute_tool
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nota.txt"
            target.write_text("contenido", encoding="utf-8")
            out = execute_tool("read_file", '{"path": "%s"}' % target, {"read_file": {"enabled": True}})
            self.assertEqual(out, "contenido")

    def test_execute_run_command_with_json_args(self):
        from tools import execute_tool
        out = execute_tool("run_command", '{"command": "echo hola"}',
                           {"run_command": {"enabled": True, "timeout": 10}})
        self.assertIn("hola", out)


if __name__ == "__main__":
    unittest.main()
