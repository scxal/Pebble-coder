"""Tests de UTF-8: acentos en E/S de terminal, ficheros legacy y keywords."""
import os
import pty
import tempfile
import tty
import unittest

from menu import _read_key
from tools import _query_keywords, read_file, run_command


class TestReadKeyUtf8(unittest.TestCase):
    """_read_key debe ensamblar caracteres UTF-8 multibyte (acentos) en una tecla."""

    def _keystrokes(self, text: str) -> str:
        master, slave = pty.openpty()
        try:
            tty.setcbreak(slave)
            os.write(master, text.encode("utf-8"))
            out = ""
            for _ in range(len(text)):
                out += _read_key(slave)
            return out
        finally:
            os.close(master)
            os.close(slave)

    def test_lowercase_accents(self):
        self.assertEqual(self._keystrokes("áéíóúñü"), "áéíóúñü")

    def test_uppercase_accents(self):
        self.assertEqual(self._keystrokes("ÁÉÍÓÚÑÜ"), "ÁÉÍÓÚÑÜ")

    def test_ascii_still_works(self):
        self.assertEqual(self._keystrokes("abc123"), "abc123")


class TestReadFileLegacyEncoding(unittest.TestCase):
    """read_file debe recuperar acentos de ficheros latin-1 (fallback vivo)."""

    def test_latin1_fallback(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write("café ñoño ÁRBOL".encode("latin-1"))
            r = read_file(path)
            self.assertIn("café", r)
            self.assertIn("ñoño", r)
            self.assertIn("ÁRBOL", r)
        finally:
            os.unlink(path)

    def test_utf8_file_untouched(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write("camión Árbol".encode("utf-8"))
            r = read_file(path)
            self.assertIn("camión", r)
            self.assertIn("Árbol", r)
        finally:
            os.unlink(path)


class TestRunCommandUtf8(unittest.TestCase):
    """run_command debe decodificar la salida como UTF-8 (independiente de la locale)."""

    def test_utf8_output(self):
        r = run_command("printf 'caf\\303\\251 \\303\\221'")
        self.assertIn("café", r)
        self.assertIn("Ñ", r)


class TestQueryKeywordsAccents(unittest.TestCase):
    """_query_keywords debe aceptar acentos en mayuscula y minuscula."""

    def test_uppercase_accents(self):
        self.assertEqual(_query_keywords("ÁRBOL LÍNEA género"), ["árbol", "línea", "género"])

    def test_lowercase_accents(self):
        self.assertEqual(_query_keywords("árbol línea género"), ["árbol", "línea", "género"])

    def test_mixed_case_accents(self):
        self.assertEqual(_query_keywords("ÁRbol líNEA"), ["árbol", "línea"])


if __name__ == "__main__":
    unittest.main()
