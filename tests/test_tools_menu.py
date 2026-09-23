"""Tests del comando /tools: menu de dos niveles para editar tools.json."""
import json
import unittest

import agent
from agent import build_tool_option_items, cmd_tools
from tests.helpers import AgentPty, ConfigGuard, TOOLS, ToolsGuard

WEB_SEARCH = {
    "enabled": True,
    "confirm": False,
    "description": "no se edita",
    "timeout": 20,
    "max_output_chars": 3000,
    "max_wiki_results": 4,
    "max_ddg_topics": 3,
    "fetch_budget": 2400,
    "auto_fetch": False,
}


class TestBuildToolOptionItems(unittest.TestCase):
    def test_web_search_rows_kinds_and_labels(self):
        tools = {"web_search": dict(WEB_SEARCH)}
        items = build_tool_option_items("web_search", tools)
        self.assertEqual(len(items), 8)  # description excluida
        kinds = [i.kind for i in items]
        self.assertEqual(kinds.count("toggle"), 3)  # enabled, confirm, auto_fetch
        self.assertEqual(kinds.count("text"), 5)    # timeout + 4 maximos/ presupuesto
        self.assertEqual(items[0].label, agent.t("label_enabled"))
        self.assertIs(items[0].value, True)         # el bool real, listo para flip()

    def test_toggle_persists_boolean_not_string(self):
        tools = {"list_files": {"enabled": True, "confirm": False, "description": "x"}}
        with ToolsGuard():
            items = build_tool_option_items("list_files", tools)
            items[0].on_change("off")  # lo que produce MenuItem.flip()
            self.assertIs(tools["list_files"]["enabled"], False)
            on_disk = json.loads(TOOLS.read_text(encoding="utf-8"))
            self.assertIs(on_disk["list_files"]["enabled"], False)  # bool, no "off"

    def test_int_row_validates_and_persists(self):
        tools = {"run_command": {"enabled": True, "confirm": True,
                                 "description": "x", "timeout": 30}}
        with ToolsGuard():
            items = build_tool_option_items("run_command", tools)
            timeout_item = items[2]  # enabled, confirm, timeout
            self.assertEqual(timeout_item.kind, "text")
            with self.assertRaises(ValueError):
                timeout_item.validate("abc")
            timeout_item.on_change(timeout_item.validate("75"))
            self.assertEqual(tools["run_command"]["timeout"], 75)
            on_disk = json.loads(TOOLS.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["run_command"]["timeout"], 75)

    def test_registered_as_slash_command(self):
        self.assertIn("/tools", agent.COMMANDS)
        self.assertIs(agent.COMMANDS["/tools"], cmd_tools)
        commands = dict(agent.load_commands())
        self.assertEqual(commands.get("/tools"), agent.t("cmd_tools"))


class TestToolsCommandE2E(unittest.TestCase):
    def test_two_level_flow_edits_and_saves(self):
        with ToolsGuard(), ConfigGuard({"language": "es"}), AgentPty() as term:
            term.read(2.0)
            term.send(b"/tools\r")
            level1 = term.read(1.5)
            with self.subTest("nivel 1: lista de herramientas"):
                self.assertIn("Herramientas (tools.json)", level1)
                self.assertIn("list_files — on", level1)

            term.send(b"\r")  # Enter sobre list_files (accion -> nivel 2)
            level2 = term.read(1.5)
            with self.subTest("nivel 2: opciones de la herramienta"):
                self.assertIn("Opciones de list_files", level2)
                self.assertIn("Habilitada", level2)

            term.send(b"\r")  # Enter sobre Habilitada -> toggle off
            toggled = term.read(1.0)
            with self.subTest("toggle aplicado y guardado como bool"):
                on_disk = json.loads(TOOLS.read_text(encoding="utf-8"))
                self.assertIs(on_disk["list_files"]["enabled"], False)

            term.send(b"q")   # cierra nivel 2 -> vuelve al nivel 1
            back = term.read(1.5)
            with self.subTest("vuelve al nivel 1 con el estado refrescado"):
                self.assertIn("Herramientas (tools.json)", back)
                self.assertIn("list_files — off", back)

            term.send(b"q")   # sale de /tools
            closed = term.read(1.0)
            self.assertIn("Menú cerrado.", closed)

            term.send(b"/exit\r")
            self.assertTrue(term.wait_exit())

        # ToolsGuard restaura tools.json al salir del bloque.
        restored = json.loads(TOOLS.read_text(encoding="utf-8"))
        self.assertIs(restored["list_files"]["enabled"], True)


if __name__ == "__main__":
    unittest.main()
