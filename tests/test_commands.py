"""E2E del autocompletado de comandos ('/' popup, filtro, Tab) y de /exit."""
import tempfile
import unittest
from pathlib import Path

from menu import _match_rank
from tests.helpers import AgentPty, ConfigGuard, FakeLLM

RESPONSE = "Thought: ok.\n\nFinal Answer:\nHOLA-OK"


def _skill(dir_path, name):
    Path(dir_path, f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: Procedimiento {name}\n---\n1. Paso uno.\n",
        encoding="utf-8")


class TestMatchRank(unittest.TestCase):
    def test_prefix_beats_substring_beats_subsequence(self):
        self.assertEqual(_match_rank("/settings", "/se"), 0)
        self.assertEqual(_match_rank("/settings", "tt"), 1)
        self.assertEqual(_match_rank("/responsive-layout", "/rlt"), 2)
        self.assertIsNone(_match_rank("/settings", "/zz"))

    def test_subsequence_respects_order(self):
        self.assertIsNone(_match_rank("/abc", "/cb"))
        self.assertEqual(_match_rank("/abc", "/ac"), 2)


class TestCommandAutocomplete(unittest.TestCase):
    def test_popup_filter_and_arrow_select_exit(self):
        with FakeLLM([RESPONSE]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)

            term.send(b"/")
            pop = term.read(1.0)
            with self.subTest("popup on '/' lists all commands"):
                self.assertIn("/settings — Configuración del agente", pop)
                self.assertIn("/tools — Editar herramientas", pop)
                self.assertIn("/exit — Salir del agente", pop)
            with self.subTest("popup hint shown"):
                self.assertIn("Enter: ejecutar", pop)

            term.send(b"s")
            with self.subTest("typing filters to /settings"):
                filt = term.read(1.0)
                self.assertIn("/settings — Configuración del agente", filt)
                self.assertNotIn("/exit — Salir del agente", filt)

            term.send(b"\r")
            with self.subTest("Enter executes highlighted command"):
                self.assertIn("Configuración del agente", term.read(2.0))

            term.send(b"q")
            term.read(1.0)

            term.send(b"/")
            term.read(0.8)
            term.send(b"\x1b[B")  # down -> /tools
            with self.subTest("arrow selects /tools"):
                self.assertIn("❯ /tools", term.read(0.8))
            term.send(b"\x1b[B")  # down -> /editor
            with self.subTest("arrow selects /editor"):
                self.assertIn("❯ /editor", term.read(0.8))
            term.send(b"\x1b[B")  # down -> /agent
            with self.subTest("arrow selects /agent"):
                self.assertIn("❯ /agent", term.read(0.8))
            term.send(b"\x1b[B")  # down -> /skills
            with self.subTest("arrow selects /skills"):
                self.assertIn("❯ /skills", term.read(0.8))
            term.send(b"\x1b[B")  # down -> /exit
            with self.subTest("arrow selects /exit"):
                self.assertIn("❯ /exit", term.read(0.8))
            term.send(b"\r")
            term.read(0.8)
            with self.subTest("executing /exit quits agent"):
                self.assertTrue(term.wait_exit())

    def test_chat_tab_completion_and_exit(self):
        with FakeLLM([RESPONSE]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)

            term.send("hola\r".encode())
            with self.subTest("plain chat text reaches the agent"):
                self.assertIn("HOLA-OK", term.read(3.0))

            term.send(b"/set\t")
            with self.subTest("Tab completes the command"):
                self.assertIn("❯ /settings", term.read(1.0))
            term.send(b"\r")
            term.read(1.5)
            term.send(b"q")
            term.read(1.0)

            term.send(b"/foo\r")
            unk = term.read(1.0)
            with self.subTest("unknown command lists all commands"):
                self.assertIn("Comando desconocido: /foo", unk)
                self.assertIn("/settings, /tools, /editor, /agent, /skills, /exit, /quit", unk)

            term.send(b"/exit\r")
            term.read(1.0)
            with self.subTest("'/exit' typed fully quits agent"):
                self.assertTrue(term.wait_exit())


    def test_cursor_indicator_after_typed_text(self):
        with FakeLLM([RESPONSE]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)

            term.send(b"ho")
            out = term.read(1.0)
            with self.subTest("block cursor drawn after typed text"):
                self.assertIn("ho\x1b[7m \x1b[0m", out)

            term.send(b"\x7f\x7f")  # borrar 'ho' antes de salir
            term.read(0.5)
            term.send(b"/exit\r")
            term.read(1.0)
            with self.subTest("agent quits normally"):
                self.assertTrue(term.wait_exit())


    def test_exit_clears_screen(self):
        with FakeLLM([RESPONSE]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)
            term.send(b"/exit\r")
            out = term.read(1.0)
            self.assertTrue(term.wait_exit())
            with self.subTest("clear screen escape emitted on exit"):
                self.assertIn("\033[2J\033[H", out + term.read(1.0))

    def test_arrow_editing_moves_cursor(self):
        with FakeLLM([RESPONSE]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)

            term.send(b"ho")
            term.read(1.0)
            term.send(b"\x1b[D")  # left -> el bloque queda sobre la 'o'
            with self.subTest("left arrow puts the block over 'o'"):
                self.assertIn("h\x1b[7mo\x1b[0m", term.read(1.0))

            term.send(b"X")
            with self.subTest("typing inserts at the cursor position"):
                self.assertIn("hX\x1b[7mo\x1b[0m", term.read(1.0))

            term.send(b"\x7f")  # backspace borra la 'X'
            with self.subTest("backspace deletes before the cursor"):
                self.assertIn("h\x1b[7mo\x1b[0m", term.read(1.0))

            term.send(b"\x04")  # Ctrl+D -> EOF -> salir
            term.read(1.0)
            with self.subTest("agent quits on Ctrl+D"):
                self.assertTrue(term.wait_exit())


    def test_fuzzy_subsequence_matches_skill_command(self):
        with tempfile.TemporaryDirectory() as ds:
            _skill(ds, "responsive-layout")
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                              "timeout": 10, "thought": "off", "observation": "off",
                              "debug": "off", "language": "es",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/rlt")  # subsecuencia: no es prefijo ni subcadena
                with self.subTest("la subsecuencia encuentra /responsive-layout"):
                    self.assertIn("/responsive-layout", term.read(1.0))
                term.send(b"\x7f\x7f\x7f\x7f")  # borra '/rlt'
                term.read(0.5)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())

    def test_popup_paginates_when_more_than_max(self):
        with tempfile.TemporaryDirectory() as ds:
            for name in ("alpha-skill", "beta-skill", "gamma-skill",
                         "delta-skill", "epsilon-skill"):
                _skill(ds, name)
            with FakeLLM([RESPONSE]) as llm, \
                 ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                              "timeout": 10, "thought": "off", "observation": "off",
                              "debug": "off", "language": "es",
                              "skills_dir": ds, "skills": []}), \
                 AgentPty() as term:
                term.read(2.0)
                term.send(b"/")
                with self.subTest("marcador inferior: hay mas comandos fuera"):
                    self.assertIn("más abajo", term.read(1.0))
                for _ in range(6):
                    term.send(b"\x1b[B")
                with self.subTest("la ventana sigue al resaltado (marcador superior)"):
                    self.assertIn("más arriba", term.read(1.0))
                term.send(b"\x7f")  # borra el '/'
                term.read(0.5)
                term.send(b"/exit\r")
                self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
