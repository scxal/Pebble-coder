"""E2E de la confirmacion por herramienta (tools.json: confirm) con LLM simulado."""
import os
import unittest

from tests.helpers import AgentPty, ConfigGuard, FakeLLM

TEST_FILE = "/tmp/pebble_test_confirm_file.txt"
CMD_MARKER = "/tmp/pebble_test_confirm_marker.txt"

RESPONSES = [
    "Thought: Necesito crear el archivo.\n\nAction: write_file\n\nInput: " + TEST_FILE + "\ncontenido-de-prueba",
    "Thought: Listo.\n\nFinal Answer:\nARCHIVO-OK",
    "Thought: Ejecutar comando.\n\nAction: run_command\n\nInput: touch " + CMD_MARKER,
    "Thought: Hecho.\n\nFinal Answer:\nCOMANDO-OK",
]


class TestToolConfirmation(unittest.TestCase):
    def setUp(self):
        for p in (TEST_FILE, CMD_MARKER):
            if os.path.exists(p):
                os.remove(p)

    def tearDown(self):
        for p in (TEST_FILE, CMD_MARKER):
            if os.path.exists(p):
                os.remove(p)

    def test_write_file_allowed_via_menu(self):
        with FakeLLM(RESPONSES[:2]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "on",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)
            term.send("escribe el archivo\r".encode())
            out = term.read(3.0)
            with self.subTest("confirm menu shown for write_file"):
                self.assertIn("¿Permitir esta acción?", out)
                self.assertIn("Sí", out)
            with self.subTest("preview shown"):
                self.assertIn("write_file", out)
                self.assertIn(TEST_FILE, out)

            term.send(b"\r")  # Enter sobre 'Sí'
            out = term.read(3.0)
            with self.subTest("file written after allow"):
                self.assertTrue(os.path.exists(TEST_FILE))
                with open(TEST_FILE) as f:
                    self.assertEqual(f.read(), "contenido-de-prueba")
            with self.subTest("observation displayed"):
                self.assertIn("written successfully", out)
            with self.subTest("final answer reached"):
                self.assertIn("ARCHIVO-OK", out)

    def test_run_command_denied_via_menu(self):
        with FakeLLM(RESPONSES[2:]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "on",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            term.read(2.0)
            term.send("ejecuta el comando\r".encode())
            out = term.read(3.0)
            with self.subTest("confirm menu shown for run_command"):
                self.assertIn("¿Permitir esta acción?", out)

            term.send(b"2\r")  # seleccionar 'No' + Enter (teclas agrupadas)
            out = term.read(3.0)
            with self.subTest("denied message shown"):
                self.assertIn("NO se ejecutó", out)
            with self.subTest("command NOT executed"):
                self.assertFalse(os.path.exists(CMD_MARKER))
            with self.subTest("final answer reached after deny"):
                self.assertIn("COMANDO-OK", out)


if __name__ == "__main__":
    unittest.main()
