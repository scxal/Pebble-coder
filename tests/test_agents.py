"""Tests de /agent: indexado y validacion de prompts adicionales en agents_dir."""
import json
import tempfile
import unittest
from pathlib import Path

import agent
import agents
from agent import cmd_agent
from tests.helpers import CONFIG, AgentPty, ConfigGuard, FakeLLM

RESPONSE = "Thought: ok.\n\nFinal Answer:\nHOLA-AGENTE"

VALID_BODY = "ACTIVA: responde siempre en MAYUSCULAS y muy breve."


def _write(dir_path, filename, text):
    p = Path(dir_path) / filename
    p.write_text(text, encoding="utf-8")
    return p


def _valid_file(dir_path, name="revisor", filename="revisor.md", body=VALID_BODY):
    text = f"---\nname: {name}\ndescription: Revisa codigo con brevedad\n---\n\n{body}\n"
    return _write(dir_path, filename, text)


class TestParseAgentFile(unittest.TestCase):
    def test_valid_agent(self):
        with tempfile.TemporaryDirectory() as d:
            info = agents.parse_agent_file(_valid_file(d))
        self.assertTrue(info.valid)
        self.assertEqual(info.name, "revisor")
        self.assertEqual(info.description, "Revisa codigo con brevedad")
        self.assertEqual(info.body, VALID_BODY)

    def test_missing_header(self):
        with tempfile.TemporaryDirectory() as d:
            info = agents.parse_agent_file(_write(d, "x.md", "solo cuerpo sin header\n"))
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "no_header")

    def test_missing_fields(self):
        with tempfile.TemporaryDirectory() as d:
            text = "---\nname: solo-nombre\n---\n\ncuerpo\n"
            info = agents.parse_agent_file(_write(d, "x.md", text))
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "missing_fields")

    def test_empty_body(self):
        with tempfile.TemporaryDirectory() as d:
            text = "---\nname: n\ndescription: d\n---\n\n"
            info = agents.parse_agent_file(_write(d, "x.md", text))
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "empty_body")

    def test_too_long(self):
        with tempfile.TemporaryDirectory() as d:
            body = "\n".join(f"linea {i}" for i in range(agents.AGENT_MAX_LINES + 5))
            text = f"---\nname: n\ndescription: d\n---\n\n{body}\n"
            info = agents.parse_agent_file(_write(d, "x.md", text))
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "too_long")

    def test_just_at_limit_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            header = ["---", "name: n", "description: d", "---", ""]
            lines = header + [f"l{i}" for i in range(agents.AGENT_MAX_LINES - len(header))]
            text = "\n".join(lines) + "\n"
            self.assertEqual(len(text.splitlines()), agents.AGENT_MAX_LINES)
            info = agents.parse_agent_file(_write(d, "x.md", text))
        self.assertTrue(info.valid)


class TestLoadAndActive(unittest.TestCase):
    def test_load_indexes_only_valid(self):
        with tempfile.TemporaryDirectory() as d:
            _valid_file(d, name="bueno", filename="bueno.md")
            _write(d, "roto.md", "sin header\n")
            infos = agents.load_agents(Path(d))
        self.assertEqual(len(infos), 2)
        self.assertEqual([i.name for i in infos if i.valid], ["bueno"])

    def test_active_prompt_returns_body(self):
        with tempfile.TemporaryDirectory() as d:
            _valid_file(d, name="mi-agente")
            cfg = {"agents_dir": d, "agent": "mi-agente"}
            self.assertEqual(agents.active_agent_prompt(cfg), VALID_BODY)

    def test_active_prompt_empty_when_none_or_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            _valid_file(d, name="mi-agente")
            self.assertEqual(agents.active_agent_prompt({"agents_dir": d, "agent": ""}), "")
            self.assertEqual(agents.active_agent_prompt({"agents_dir": d, "agent": "otro"}), "")

    def test_missing_dir_is_empty(self):
        self.assertEqual(agents.load_agents(Path("/no/existe/xyz")), [])


class TestRegistration(unittest.TestCase):
    def test_registered_as_slash_command(self):
        self.assertIn("/agent", agent.COMMANDS)
        self.assertIs(agent.COMMANDS["/agent"], cmd_agent)
        commands = dict(agent.load_commands())
        self.assertEqual(commands.get("/agent"), agent.t("cmd_agent"))


class TestAgentCommandE2E(unittest.TestCase):
    def test_select_agent_indexes_and_injects_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            _valid_file(d, name="revisor")
            _write(d, "roto.md", "sin header\n")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": d, "agent": ""}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/agent\r")
                menu = term.read(1.5)
                with self.subTest("selector muestra el agente valido"):
                    self.assertIn("revisor", menu)
                    self.assertIn("Agentes (prompts adicionales)", menu)
                with self.subTest("el fichero no compliente se ignora con aviso"):
                    self.assertIn("roto.md", menu)

                term.send(b"\r")  # Enter sobre el agente
                picked = term.read(1.0)
                with self.subTest("aviso de agente activado"):
                    self.assertIn(agent.t("agent_selected").format(name="revisor"), picked)
                with self.subTest("agent persistido en config.json"):
                    self.assertEqual(json.loads(CONFIG.read_text())["agent"], "revisor")

                term.send("hola\r".encode())
                out = term.read(3.0)
                with self.subTest("respuesta del modelo"):
                    self.assertIn("HOLA-AGENTE", out)
                with self.subTest("prompt adicional inyectado en el system prompt"):
                    system = llm.requests[0]["messages"][0]
                    self.assertEqual(system["role"], "system")
                    self.assertIn(VALID_BODY, system["content"])

                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_no_valid_agents_message(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "roto.md", "sin header\n")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": d, "agent": ""}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/agent\r")
                menu = term.read(1.5)
                with self.subTest("avisa que no hay agentes validos"):
                    self.assertIn(agent.t("agent_none_found"), menu)
                term.send(b"q")  # cerrar menu
                term.read(1.0)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_prompt_shows_active_agent_name(self):
        with tempfile.TemporaryDirectory() as d:
            _valid_file(d, name="revisor")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": d, "agent": "revisor"}), \
                 AgentPty() as term:
                out = term.read(2.0)
                with self.subTest("prompt nombra al agente activo"):
                    self.assertIn("Tú - revisor > ", out)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
