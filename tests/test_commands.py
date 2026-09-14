"""E2E del autocompletado de comandos ('/' popup, filtro, Tab) y de /exit."""
import unittest

from tests.helpers import AgentPty, ConfigGuard, FakeLLM

RESPONSE = "Thought: ok.\n\nFinal Answer:\nHOLA-OK"


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
            with self.subTest("popup on '/' lists both commands"):
                self.assertIn("/settings — Configuración del agente", pop)
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
                self.assertIn("/settings, /exit, /quit", unk)

            term.send(b"/exit\r")
            term.read(1.0)
            with self.subTest("'/exit' typed fully quits agent"):
                self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
