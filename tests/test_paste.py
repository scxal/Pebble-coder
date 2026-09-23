"""Tests de pegado multilinea (bracketed paste) en el REPL."""
import os
import pty
import termios
import tty
import unittest

from menu import _read_key, _read_paste, _wrapped_rows
from tests.helpers import AgentPty, ConfigGuard, FakeLLM


def _open_raw_pty():
    """pty no canonico cuya linea NO traduce \\r (ICRNL), para probar CRLF literal."""
    master, slave = pty.openpty()
    tty.setcbreak(slave)
    attrs = termios.tcgetattr(slave)
    attrs[0] &= ~(termios.ICRNL | termios.INLCR | termios.IGNCR)
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    return master, slave


class TestReadPaste(unittest.TestCase):
    def test_multiline_payload_with_crlf_is_normalized(self):
        master, slave = _open_raw_pty()
        try:
            os.write(master, b"uno\r\ndos\nthree\x1b[201~")
            self.assertEqual(_read_paste(slave), "uno\ndos\nthree")
        finally:
            os.close(master)
            os.close(slave)

    def test_payload_stops_at_terminator(self):
        master, slave = _open_raw_pty()
        try:
            os.write(master, b"a\nb\x1b[201~tecleado-despues")
            self.assertEqual(_read_paste(slave), "a\nb")
            # lo posterior al terminador sigue disponible para _read_key
            self.assertEqual(_read_key(slave), "t")
        finally:
            os.close(master)
            os.close(slave)

    def test_without_terminator_returns_what_arrived(self):
        master, slave = _open_raw_pty()
        try:
            os.write(master, b"solo texto")
            self.assertEqual(_read_paste(slave), "solo texto")  # gap timeout
        finally:
            os.close(master)
            os.close(slave)

    def test_read_key_detects_paste_start(self):
        master, slave = pty.openpty()
        try:
            tty.setcbreak(slave)
            os.write(master, b"\x1b[200~")
            self.assertEqual(_read_key(slave), "paste")
        finally:
            os.close(master)
            os.close(slave)


class TestWrappedRows(unittest.TestCase):
    def test_single_line_matches_previous_formula(self):
        self.assertEqual(_wrapped_rows("abc", 80), 1)          # ceil((3+1)/80)
        self.assertEqual(_wrapped_rows("x" * 200, 80), 3)      # ceil(201/80)

    def test_explicit_newlines_add_rows(self):
        self.assertEqual(_wrapped_rows("a\nb", 80), 2)
        self.assertEqual(_wrapped_rows("a\n\nb", 80), 3)


class TestPasteE2E(unittest.TestCase):
    def test_multiline_paste_is_one_prompt(self):
        resp = "Thought: ok.\n\nFinal Answer:\nMULTI-OK"
        with FakeLLM([resp]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1",
                          "max_iterations": 5, "timeout": 10,
                          "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}), \
             AgentPty() as term:
            first = term.read(2.0)
            with self.subTest("bracketed paste activo en el prompt"):
                self.assertIn("\x1b[?2004h", first)

            term.send(b"\x1b[200~linea uno\nlinea dos\x1b[201~")
            pasted = term.read(1.0)
            with self.subTest("ambas lineas en el buffer, sin enviar nada"):
                # ONSCR del pty muestra los \n del buffer como \r\n en la salida
                self.assertIn("linea uno\r\nlinea dos", pasted)
                self.assertEqual(len(llm.requests), 0)

            term.send(b"\r")  # Enter real: UN solo envio con todo el texto
            term.read(2.5)
            with self.subTest("una unica peticion con las dos lineas"):
                self.assertEqual(len(llm.requests), 1)
                users = [m for m in llm.requests[0]["messages"]
                         if m["role"] == "user"]
                self.assertEqual(len(users), 1)
                self.assertIn("linea uno\nlinea dos", users[0]["content"])

            term.send(b"/exit\r")
            self.assertTrue(term.wait_exit())


if __name__ == "__main__":
    unittest.main()
