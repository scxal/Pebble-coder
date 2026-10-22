"""E2E del bucle ReAct con formatos de tool-call de Qwen (Hermes) y DeepSeek."""
import tempfile
import unittest
from pathlib import Path

import agent
import pbl_home
from agent import run_react_agent
from tests.helpers import FakeLLM, ConfigGuard


def _config(base_url):
    return {
        "base_url": base_url,
        "max_iterations": 5,
        "timeout": 10,
        "thought": "off",
        "observation": "off",
        "debug": "off",
        "language": "es",
    }


class TestHermesAgentLoop(unittest.TestCase):
    def test_hermes_tool_call_is_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nota.txt"
            target.write_text("hola mundo", encoding="utf-8")
            call = ('<tool_call>\n{"name": "read_file", "arguments": {"path": "%s"}}\n</tool_call>'
                    % target)
            final = "<final_answer>YA LEIDO</final_answer>"
            with FakeLLM([call, final]) as llm, \
                 ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"), format="hermes")):
                config = agent.load_config(str(pbl_home.config_path()))
                tools_config = {"read_file": {"enabled": True, "confirm": False}}

                result = run_react_agent("lee el archivo", config, tools_config, [])

                self.assertEqual(result, "YA LEIDO")
                messages = llm.requests[1]["messages"]
                self.assertTrue(any("hola mundo" in (m.get("content") or "") for m in messages))


class TestDeepSeekAgentLoop(unittest.TestCase):
    def test_deepseek_tool_call_is_executed(self):
        call = ("<｜tool▁calls▁begin｜>\n\n<｜tool▁call▁begin｜>\nrun_command\n<｜tool▁sep｜>\n"
                '{"command": "echo hola-deepseek"}\n<｜tool▁call▁end｜>\n\n<｜tool▁calls▁end｜>')
        final = "<final_answer>OK</final_answer>"
        with FakeLLM([call, final]) as llm, \
             ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"), format="deepseek")):
            config = agent.load_config(str(pbl_home.config_path()))
            tools_config = {"run_command": {"enabled": True, "confirm": False, "timeout": 10}}

            result = run_react_agent("ejecuta echo", config, tools_config, [])

            self.assertEqual(result, "OK")
            messages = llm.requests[1]["messages"]
            self.assertTrue(any("hola-deepseek" in (m.get("content") or "") for m in messages))


class TestAutoAgentLoop(unittest.TestCase):
    def test_auto_detects_hermes_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nota.txt"
            target.write_text("auto-contenido", encoding="utf-8")
            call = '<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>' % target
            final = "<final_answer>AUTO OK</final_answer>"
            with FakeLLM([call, final]) as llm, \
                 ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"), format="auto")):
                config = agent.load_config(str(pbl_home.config_path()))
                tools_config = {"read_file": {"enabled": True, "confirm": False}}

                result = run_react_agent("lee el archivo", config, tools_config, [])

                self.assertEqual(result, "AUTO OK")
                messages = llm.requests[1]["messages"]
                self.assertTrue(any("auto-contenido" in (m.get("content") or "") for m in messages))


class TestNonInteractiveConfirm(unittest.TestCase):
    def _call(self, target):
        return "[Action] write_file\n[Input] %s\nhola desde el agente" % target

    def test_denied_without_terminal(self):
        import io
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, FakeLLM([
            self._call(Path(tmp) / "x.txt"), "Final Answer: denegado",
        ]) as llm, ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"), format="text")):
            config = agent.load_config(str(pbl_home.config_path()))
            tools_config = {"write_file": {"enabled": True, "confirm": True}}
            with mock.patch("sys.stdin", io.StringIO("")):
                result = run_react_agent("escribe", config, tools_config, [])
            self.assertEqual(result, "denegado")
            self.assertFalse((Path(tmp) / "x.txt").exists())

    def test_auto_approve_via_config(self):
        with tempfile.TemporaryDirectory() as tmp, FakeLLM([
            self._call(Path(tmp) / "y.txt"), "Final Answer: escrito",
        ]) as llm, ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"),
                                    format="text", _auto_approve=True)):
            config = agent.load_config(str(pbl_home.config_path()))
            tools_config = {"write_file": {"enabled": True, "confirm": True}}
            result = run_react_agent("escribe", config, tools_config, [])
            self.assertEqual(result, "escrito")
            self.assertEqual((Path(tmp) / "y.txt").read_text(encoding="utf-8"),
                             "hola desde el agente")


class TestCliYesFlag(unittest.TestCase):
    def test_yes_flag_allows_confirm(self):
        import io
        import sys
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "z.txt"
            with FakeLLM(["[Action] write_file\n[Input] %s\ncontenido cli" % target,
                          "Final Answer: hecho"]) as llm, \
                 ConfigGuard(dict(_config(f"http://127.0.0.1:{llm.port}/v1"), format="text")):
                with mock.patch.object(sys, "argv", ["agent.py", "-y", "escribe"]), \
                     mock.patch("sys.stdin", io.StringIO("")):
                    agent.main()
            self.assertEqual(target.read_text(encoding="utf-8"), "contenido cli")


if __name__ == "__main__":
    unittest.main()
