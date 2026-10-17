"""Tests del comando /editor: abre el editor configurado sobre un tmp y usa
su contenido como prompt (multilinea) del siguiente turno."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent
from agent import cmd_editor
from tests.helpers import AgentPty, ConfigGuard, FakeLLM

RESPONSE = "Thought: ok.\n\nFinal Answer:\nHOLA-EDITOR"


def _editor_script(dir_path, body: str) -> str:
    """Crea un script ejecutable que escribe `body` en el fichero que recibe."""
    script = Path(dir_path) / "fake_editor.sh"
    script.write_text("#!/bin/sh\ncat > \"$1\" <<'PBC_EOF'\n" + body + "PBC_EOF\n",
                      encoding="utf-8")
    script.chmod(0o755)
    return str(script)


class TestCmdEditorUnit(unittest.TestCase):
    def test_content_returned_as_prompt_with_newlines(self):
        tools = {"list_files": {}}
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("agent.statistics.deactivate_bar"):
            editor = _editor_script(tmp, "linea uno\nlinea dos\n")
            out_tools, prompt = cmd_editor({"editor": editor}, tools)
        self.assertIs(out_tools, tools)
        self.assertEqual(prompt, "linea uno\nlinea dos")

    def test_default_editor_is_vi_when_key_missing(self):
        seen = {}

        def fake_run(argv, *a, **k):
            seen["argv"] = argv
            return mock.Mock(returncode=0)

        with mock.patch("agent.subprocess.run", side_effect=fake_run), \
             mock.patch("agent.statistics.deactivate_bar"):
            out_tools, prompt = cmd_editor({}, {"t": {}})
        self.assertEqual(seen["argv"][0], "vi")
        self.assertIsNone(prompt)  # fichero vacio -> cancelado

    def test_editor_command_from_config_with_args(self):
        seen = {}

        def fake_run(argv, *a, **k):
            seen["argv"] = argv
            return mock.Mock(returncode=0)

        with mock.patch("agent.subprocess.run", side_effect=fake_run), \
             mock.patch("agent.statistics.deactivate_bar"):
            cmd_editor({"editor": "nano -w"}, {"t": {}})
        self.assertEqual(seen["argv"][0], "nano")
        self.assertEqual(seen["argv"][1], "-w")

    def test_empty_buffer_cancels(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("agent.statistics.deactivate_bar"):
            editor = _editor_script(tmp, "")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                out_tools, prompt = cmd_editor({"editor": editor}, {"t": {}})
        self.assertIsNone(prompt)
        self.assertEqual(buf.getvalue().strip(), agent.t("editor_empty"))

    def test_editor_not_found_returns_no_prompt(self):
        with mock.patch("agent.subprocess.run", side_effect=FileNotFoundError("vi")), \
             mock.patch("agent.statistics.deactivate_bar"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                out_tools, prompt = cmd_editor({"editor": "vi"}, {"t": {}})
        self.assertIsNone(prompt)
        self.assertIn("vi", buf.getvalue())

    def test_registered_as_slash_command(self):
        self.assertIn("/editor", agent.COMMANDS)
        self.assertIs(agent.COMMANDS["/editor"], cmd_editor)
        commands = dict(agent.load_commands())
        self.assertEqual(commands.get("/editor"), agent.t("cmd_editor"))


class TestEditorCommandE2E(unittest.TestCase):
    def test_editor_content_is_sent_as_single_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            editor = _editor_script(tmp, "primera linea\nsegunda linea\n")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "editor": editor}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/editor\r")
                out = term.read(3.0)
                with self.subTest("el turno del editor se ejecuta"):
                    self.assertIn("HOLA-EDITOR", out)

                with self.subTest("el prompt lleva ambas lineas, sin comandos"):
                    self.assertEqual(len(llm.requests), 1)
                    last = llm.requests[0]["messages"][-1]
                    self.assertEqual(last["role"], "user")
                    self.assertIn("primera linea", last["content"])
                    self.assertIn("segunda linea", last["content"])

                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_empty_editor_cancels_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            editor = _editor_script(tmp, "")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "editor": editor}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/editor\r")
                out = term.read(2.0)
                with self.subTest("avisa de editor vacio"):
                    self.assertIn(agent.t("editor_empty"), out)
                with self.subTest("no se llama al modelo"):
                    self.assertEqual(llm.requests, [])

                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
