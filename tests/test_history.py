"""Tests de memoria de sesion: el historial de turnos viaja al LLM."""
import unittest

import agent
from agent import _HISTORY_MAX_MESSAGES, run_react_agent, update_history
from tools import load_tools_config
from tests.helpers import FakeLLM, ConfigGuard

RESP1 = "Thought: ok.\n\nFinal Answer:\nME-LLAMO-SANDIA"
RESP2 = "Thought: ok.\n\nFinal Answer:\nHECHO"


class TestSessionHistory(unittest.TestCase):
    def _config(self):
        return agent.load_config(str(agent._SCRIPT_DIR / "config.json"))

    def test_second_turn_includes_previous_exchange(self):
        with FakeLLM([RESP1, RESP2]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}):
            config = self._config()
            tools_config = load_tools_config(str(agent._SCRIPT_DIR / "tools.json"))
            history = []

            answer = run_react_agent("Mi nombre es Sandia", config, tools_config, history)
            update_history(history, "Mi nombre es Sandia", answer)
            run_react_agent("¿Cual es mi nombre?", config, tools_config, history)

            msgs = llm.requests[1]["messages"]
            self.assertEqual(msgs[0]["role"], "system")
            self.assertIn({"role": "user", "content": "Mi nombre es Sandia"}, msgs)
            self.assertIn({"role": "assistant", "content": "ME-LLAMO-SANDIA"}, msgs)
            self.assertEqual(msgs[-1]["role"], "user")
            self.assertEqual(msgs[-1]["content"], "¿Cual es mi nombre?")

    def test_first_turn_has_no_history(self):
        with FakeLLM([RESP1]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}):
            config = self._config()
            tools_config = load_tools_config(str(agent._SCRIPT_DIR / "tools.json"))

            run_react_agent("Hola", config, tools_config, [])

            msgs = llm.requests[0]["messages"]
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[0]["role"], "system")
            self.assertEqual(msgs[1]["content"], "Hola")


class TestFormatErrorCorrection(unittest.TestCase):
    def test_malformed_response_is_recorded_before_correction(self):
        malformed = "Your name is Edgar."  # sin Final Answer ni Action -> error de parser
        good = "Thought: ok.\n\nFinal Answer:\nEDGAR"
        with FakeLLM([malformed, good]) as llm, \
             ConfigGuard({"base_url": f"http://127.0.0.1:{llm.port}/v1", "max_iterations": 5,
                          "timeout": 10, "thought": "off", "observation": "off",
                          "debug": "off", "language": "es"}):
            config = agent.load_config(str(agent._SCRIPT_DIR / "config.json"))
            tools_config = load_tools_config(str(agent._SCRIPT_DIR / "tools.json"))

            result = run_react_agent("¿Cual es mi nombre?", config, tools_config, [])

            self.assertEqual(result, "EDGAR")
            msgs = llm.requests[1]["messages"]
            self.assertEqual(msgs[-2]["role"], "assistant")
            self.assertEqual(msgs[-2]["content"], malformed)
            self.assertEqual(msgs[-1]["role"], "user")
            self.assertIn("FORMAT ERROR", msgs[-1]["content"])


class TestUpdateHistory(unittest.TestCase):
    def test_trims_to_limit_keeping_recent_pairs(self):
        h = []
        for i in range(5):
            update_history(h, f"pregunta {i}", f"respuesta {i}")
        self.assertEqual(len(h), _HISTORY_MAX_MESSAGES)
        self.assertEqual(h[0]["content"], f"pregunta {5 - _HISTORY_MAX_MESSAGES // 2}")
        self.assertEqual(h[-1]["content"], "respuesta 4")

    def test_empty_answer_recorded(self):
        h = []
        update_history(h, "pregunta", "")
        self.assertEqual(h[1]["content"], "")


if __name__ == "__main__":
    unittest.main()
