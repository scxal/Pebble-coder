"""Utilidades compartidas por la suite de tests (solo stdlib + requests).

- ConfigGuard: respalda config.json, aplica overrides y restaura al salir.
- FakeLLM: servidor SSE compatible con OpenAI con respuestas guionizadas.
- AgentPty: ejecuta agent.py en una pty real (teclas y salida byte a byte).
"""
import codecs
import fcntl
import json
import os
import pty
import select
import struct
import sys
import termios
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CONFIG = PROJECT / "config.json"

if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

# Valores deterministas para los tests que mutan la configuracion.
KNOWN_CONFIG = {
    "language": "es",
    "temperature": 0.2,
    "max_iterations": 20,
    "timeout": 120,
    "format": "text",
    "debug": "off",
    "thought": "on",
    "observation": "off",
}


def net_ok(timeout=4):
    """True si hay salida a internet (para saltar tests de red)."""
    try:
        urllib.request.urlopen("https://api.duckduckgo.com/?q=test&format=json", timeout=timeout)
        return True
    except Exception:
        return False


class ConfigGuard:
    """Respalda config.json, escribe overrides conocidos y restaura al salir."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.original = None

    def __enter__(self):
        self.original = CONFIG.read_bytes()
        cfg = json.loads(self.original)
        cfg.update(self.overrides)
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return cfg

    def __exit__(self, *exc):
        CONFIG.write_bytes(self.original)
        return False


class FakeLLM:
    """Servidor SSE minimo que devuelve las respuestas guionizadas en orden.

    `usage` (opcional) se inyecta como campo `usage` del chunk (para probar
    el conteo de tokens); `delay` (opcional) espera antes de responder.
    """

    def __init__(self, responses, usage=None, delay=0):
        self.responses = responses
        self.usage = usage
        self.delay = delay
        self.count = 0
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    outer.requests.append(json.loads(body))
                except Exception:
                    outer.requests.append(None)
                outer.count += 1
                if outer.delay:
                    time.sleep(outer.delay)
                content = responses[min(outer.count, len(responses)) - 1]
                chunk = {"choices": [{"delta": {"content": content}}]}
                if outer.usage is not None:
                    chunk["usage"] = outer.usage
                payload = json.dumps(chunk) + "\n"
                sse = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(sse)))
                self.end_headers()
                self.wfile.write(sse)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self):
        return self.server.server_address[1]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


class AgentPty:
    """Lanza agent.py en una pty y permite enviar teclas / leer salida."""

    def __init__(self):
        self.transcript = []
        self.pid = None
        self.fd = None

    def __enter__(self):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(PROJECT)
            os.execvp("python3", ["python3", "agent.py"])
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        except OSError:
            pass
        return self

    def read(self, timeout=1.0):
        """Lee la salida disponible durante `timeout` segundos."""
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        out = ""
        while True:
            r, _, _ = select.select([self.fd], [], [], timeout)
            if not r:
                break
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                break
            if not data:
                break
            out += decoder.decode(data)
        self.transcript.append(out)
        return out

    def send(self, data):
        os.write(self.fd, data)

    def _reaped(self):
        try:
            done, _ = os.waitpid(self.pid, os.WNOHANG)
            return bool(done)
        except ChildProcessError:
            return True

    def wait_exit(self, timeout=15):
        """Espera la salida del proceso; lo mata si no termina a tiempo."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._reaped():
                return True
            time.sleep(0.1)
        try:
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        return False

    def __exit__(self, *exc):
        if self.pid and not self._reaped():
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        return False
