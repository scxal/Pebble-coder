"""Tests de /skills: indexado/validacion y acceso por agente (reglas 1 y 2)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import agent
import skills
from agent import cmd_skills
from tests.helpers import CONFIG, AgentPty, ConfigGuard, FakeLLM

RESPONSE = "Thought: ok.\n\nFinal Answer:\nHOLA-SKILL"

ALPHA_BODY = "ALPHA-PROCEDURE: paso uno, paso dos."
BETA_BODY = "BETA-PROCEDURE: otro procedimiento."


def _write(dir_path, filename, text):
    p = Path(dir_path) / filename
    p.write_text(text, encoding="utf-8")
    return p


def _skill(dir_path, name, body, filename=None):
    text = f"---\nname: {name}\ndescription: skill {name}\n---\n\n{body}\n"
    return _write(dir_path, filename or f"{name}.md", text)


def _agent(dir_path, name, skills_names, filename=None):
    skills_field = f"skills: {', '.join(skills_names)}\n" if skills_names else ""
    text = f"---\nname: {name}\ndescription: agente {name}\n{skills_field}---\n\nAgent body\n"
    return _write(dir_path, filename or f"{name}.md", text)


class TestSkillsParsing(unittest.TestCase):
    def test_valid_skill(self):
        with tempfile.TemporaryDirectory() as d:
            info = skills.parse_skill_file(_skill(d, "alpha", ALPHA_BODY))
        self.assertTrue(info.valid)
        self.assertEqual(info.name, "alpha")
        self.assertEqual(info.body, ALPHA_BODY)

    def test_non_compliant_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(skills.parse_skill_file(
                _write(d, "a.md", "sin header\n")).reason, "no_header")
            self.assertEqual(skills.parse_skill_file(
                _write(d, "b.md", "---\nname: x\n---\n\nbody\n")).reason, "missing_fields")
            self.assertEqual(skills.parse_skill_file(
                _write(d, "c.md", "---\nname: x\ndescription: y\n---\n\n")).reason, "empty_body")
            long_body = "\n".join(f"l{i}" for i in range(skills.SKILL_MAX_LINES + 5))
            self.assertEqual(skills.parse_skill_file(
                _write(d, "d.md", f"---\nname: x\ndescription: y\n---\n\n{long_body}\n")).reason,
                "too_long")

    def test_load_indexes_only_valid(self):
        with tempfile.TemporaryDirectory() as d:
            _skill(d, "alpha", ALPHA_BODY)
            _write(d, "roto.md", "sin header\n")
            infos = skills.load_skills(Path(d))
        self.assertEqual([i.name for i in infos if i.valid], ["alpha"])

    def test_enabled_names_from_list_and_string(self):
        self.assertEqual(skills.enabled_names({"skills": ["a", "b"]}), ["a", "b"])
        self.assertEqual(skills.enabled_names({"skills": "a, b"}), ["a", "b"])
        self.assertEqual(skills.enabled_names({}), [])


class TestAgentSkillsField(unittest.TestCase):
    def test_agent_parses_skills_list(self):
        import agents
        with tempfile.TemporaryDirectory() as d:
            info = agents.parse_agent_file(_agent(d, "a", ["x", "y"]))
            info2 = agents.parse_agent_file(
                _write(d, "b.md", "---\nname: b\ndescription: d\nskills: [p, q]\n---\n\nbody\n"))
            info3 = agents.parse_agent_file(
                _write(d, "c.md", "---\nname: c\ndescription: d\n---\n\nbody\n"))
        self.assertEqual(info.skills, ["x", "y"])
        self.assertEqual(info2.skills, ["p", "q"])
        self.assertEqual(info3.skills, [])


class TestScopingAndInjection(unittest.TestCase):
    def test_visible_rules_and_active_prompt(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)

            base = {"agents_dir": da, "skills_dir": ds}
            # Regla 1: con agente, solo sus skills.
            with_agent = dict(base, agent="writer", skills=["alpha", "beta"])
            self.assertEqual([i.name for i in skills.visible_skills(with_agent)], ["alpha"])
            # beta esta "enabled" pero no permitida -> no se inyecta.
            self.assertIn(ALPHA_BODY, skills.active_skills_prompt(with_agent))
            self.assertNotIn(BETA_BODY, skills.active_skills_prompt(with_agent))

            # Regla 2: sin agente, todas las skills validas.
            no_agent = dict(base, agent="", skills=["beta"])
            self.assertEqual([i.name for i in skills.visible_skills(no_agent)], ["alpha", "beta"])
            prompt = skills.active_skills_prompt(no_agent)
            self.assertIn(BETA_BODY, prompt)
            self.assertNotIn(ALPHA_BODY, prompt)

    def test_no_enabled_skills_means_no_prompt(self):
        with tempfile.TemporaryDirectory() as ds:
            _skill(ds, "alpha", ALPHA_BODY)
            self.assertEqual(skills.active_skills_prompt({"skills_dir": ds, "skills": []}), "")


class TestRegistration(unittest.TestCase):
    def test_registered_as_slash_command(self):
        self.assertIn("/skills", agent.COMMANDS)
        self.assertIs(agent.COMMANDS["/skills"], cmd_skills)
        commands = dict(agent.load_commands())
        self.assertEqual(commands.get("/skills"), agent.t("cmd_skills"))


class TestSkillsCommandE2E(unittest.TestCase):
    def test_agent_scopes_list_and_injects_selected(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": da, "agent": "writer",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/skills\r")
                menu = term.read(1.5)
                with self.subTest("regla 1: solo las skills del agente"):
                    self.assertIn("alpha", menu)
                    self.assertNotIn("beta", menu)
                    self.assertIn("Skills (procedimientos)", menu)

                term.send(b"\r")  # toggle alpha on
                term.read(1.0)
                with self.subTest("skill activada persistida en config.json"):
                    self.assertEqual(json.loads(CONFIG.read_text())["skills"], ["alpha"])

                term.send(b"q")   # cerrar el menu de skills
                term.read(1.0)
                term.send("hola\r".encode())
                out = term.read(3.0)
                with self.subTest("respuesta del modelo"):
                    self.assertIn("HOLA-SKILL", out)
                with self.subTest("procedimiento inyectado en el system prompt"):
                    system = llm.requests[0]["messages"][0]["content"]
                    self.assertIn(ALPHA_BODY, system)
                    self.assertNotIn(BETA_BODY, system)

                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_no_agent_lists_all_skills(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": da, "agent": "",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/skills\r")
                menu = term.read(1.5)
                with self.subTest("regla 2: sin agente, todas las skills"):
                    self.assertIn("alpha", menu)
                    self.assertIn("beta", menu)
                term.send(b"q")
                term.read(1.0)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())


class TestSkillCommands(unittest.TestCase):
    def test_skill_commands_lists_only_allowed(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            with_agent = {"agents_dir": da, "skills_dir": ds, "agent": "writer"}
            self.assertEqual([n for n, _ in agent.skill_commands(with_agent)], ["/alpha"])
            no_agent = {"agents_dir": da, "skills_dir": ds, "agent": ""}
            self.assertEqual([n for n, _ in agent.skill_commands(no_agent)], ["/alpha", "/beta"])

    def test_handle_command_runs_allowed_skill_and_rejects_others(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            cfg = {"agents_dir": da, "skills_dir": ds, "agent": "writer", "skills": []}
            _, prompt = agent.handle_command("/alpha", cfg, {"t": {}})
            self.assertEqual(prompt, ALPHA_BODY)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _, bad = agent.handle_command("/beta", cfg, {"t": {}})
            self.assertIsNone(bad)  # beta no permitida por el agente


class TestSkillCommandE2E(unittest.TestCase):
    def test_autocomplete_lists_skill_and_runs_procedure(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": da, "agent": "writer",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/al")
                pop = term.read(1.0)
                with self.subTest("autocompleta a la skill permitida"):
                    self.assertIn("/alpha", pop)
                    self.assertNotIn("/beta", pop)

                term.send(b"\r")  # Enter: ejecuta el comando resaltado
                out = term.read(3.0)
                with self.subTest("aviso de ejecucion"):
                    self.assertIn(agent.t("skill_running").format(name="/alpha"), out)
                with self.subTest("respuesta del modelo"):
                    self.assertIn("HOLA-SKILL", out)
                with self.subTest("procedimiento enviado como prompt del turno"):
                    last = llm.requests[0]["messages"][-1]
                    self.assertEqual(last["role"], "user")
                    self.assertIn(ALPHA_BODY, last["content"])

                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_command_list_refreshes_after_agent_change(self):
        with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as ds:
            _agent(da, "writer", ["alpha"])
            _skill(ds, "alpha", ALPHA_BODY)
            _skill(ds, "beta", BETA_BODY)
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                              "max_iterations": 5, "timeout": 10, "thought": "off",
                              "observation": "off", "debug": "off", "language": "es",
                              "agents_dir": da, "agent": "writer",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/al")
                pop = term.read(1.0)
                with self.subTest("con agente: solo /alpha"):
                    self.assertIn("/alpha", pop)
                    self.assertNotIn("/beta", pop)

                term.send(b"\x7f\x7f\x7f")  # borra '/al'
                term.read(0.5)
                term.send(b"/agent\r")
                menu = term.read(1.2)
                with self.subTest("menu de /agent con opcion None"):
                    self.assertIn("Ninguno", menu)
                term.send(b"2")             # fila 2 = Ninguno
                term.read(0.5)
                term.send(b"\r")            # ejecuta -> desactiva agente
                term.read(1.0)
                with self.subTest("agente desactivado"):
                    self.assertEqual(json.loads(CONFIG.read_text())["agent"], "")

                term.send(b"/be")
                pop2 = term.read(1.0)
                with self.subTest("lista refrescada: ahora aparece /beta sin reiniciar"):
                    self.assertIn("/beta", pop2)

                term.send(b"\x7f\x7f\x7f")
                term.read(0.4)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
