"""Tests de la barra de estadisticas y del tiempo de peticion al LLM."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import statistics

import agent
from agent import run_react_agent
from tests.helpers import AgentPty, ConfigGuard, FakeLLM, PROJECT

RESP = "Thought: ok.\n\nFinal Answer:\nOK"


class _StatsCase(unittest.TestCase):
    def setUp(self):
        statistics.reset()

    def tearDown(self):
        statistics.reset()


class TestEnabled(_StatsCase):
    def test_default_on_when_unbound(self):
        self.assertTrue(statistics.enabled())

    def test_on_off_strings_and_bool(self):
        statistics.bind({"stats": "off"})
        self.assertFalse(statistics.enabled())
        statistics.bind({"stats": "on"})
        self.assertTrue(statistics.enabled())
        statistics.bind({"stats": False})
        self.assertFalse(statistics.enabled())
        statistics.bind({})
        self.assertTrue(statistics.enabled())


class TestTiming(_StatsCase):
    def test_answer_timing_in_flight_and_done(self):
        statistics.begin_answer()
        time.sleep(0.02)
        in_flight = statistics.last_answer_s()
        self.assertIsNotNone(in_flight)
        self.assertGreaterEqual(in_flight, 0.02)
        statistics.end_answer()
        self.assertGreaterEqual(statistics.last_answer_s(), 0.02)
        statistics.begin_answer()
        statistics.end_answer()
        self.assertGreater(statistics.last_answer_s(), 0)

    def test_request_tps_from_usage(self):
        statistics.begin_request()
        time.sleep(0.05)
        statistics.note_usage({"prompt_tokens": 100, "completion_tokens": 50})
        statistics.end_request("cualquier texto")
        self.assertGreaterEqual(statistics.last_req_s(), 0.05)
        self.assertEqual(statistics.last_completion_tokens(), 50)
        self.assertAlmostEqual(statistics.last_tps(),
                               50 / statistics.last_req_s(), places=5)

    def test_request_tps_estimated_from_chars_without_usage(self):
        statistics.begin_request()
        time.sleep(0.02)
        statistics.end_request("x" * 400)  # ~100 tokens estimados
        self.assertGreater(statistics.last_req_s(), 0)
        self.assertIsNone(statistics.last_completion_tokens())
        self.assertGreater(statistics.last_tps(), 0)

    def test_end_request_without_begin_is_noop(self):
        statistics.end_request("x")
        self.assertIsNone(statistics.last_req_s())


class TestContext(_StatsCase):
    def test_estimate_then_exact_usage_override(self):
        statistics.note_context([
            {"role": "system", "content": "a" * 4000},
            {"role": "user", "content": "b" * 80},
        ])
        self.assertEqual(statistics.last_ctx(), 1020)
        statistics.note_usage({"prompt_tokens": 333, "completion_tokens": 7})
        self.assertEqual(statistics.last_ctx(), 333)
        statistics.note_context([{"role": "user", "content": "c" * 40}])
        self.assertEqual(statistics.last_ctx(), 10)


class TestSamplers(_StatsCase):
    def test_cpu_percent_between_two_samples(self):
        prev = statistics.parse_proc_stat("cpu 100 0 100 800 0 0 0 0")
        cur = statistics.parse_proc_stat("cpu 200 0 200 1000 0 0 0 0")
        self.assertEqual(prev, (800, 1000))
        self.assertEqual(cur, (1000, 1400))
        self.assertAlmostEqual(statistics._cpu_percent(prev, cur), 50.0)

    def test_meminfo_parse_and_ram_sample(self):
        text = "MemTotal:       16384000 kB\nMemAvailable:   8192000 kB\n"
        self.assertEqual(statistics.parse_proc_meminfo(text), (16384000, 8192000))
        fallback = ("MemTotal: 1000 kB\nMemFree: 400 kB\n"
                    "Buffers: 100 kB\nCached: 200 kB\n")
        self.assertEqual(statistics.parse_proc_meminfo(fallback)[1], 700)
        self.assertRegex(statistics._sample_ram(), r"^\d+\.\dG/\d+G$")

    def test_gpu_sysfs_glob_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            busy = Path(td) / "card0" / "device" / "gpu_busy_percent"
            busy.parent.mkdir(parents=True)
            busy.write_text("67\n", encoding="utf-8")
            pattern = str(Path(td) / "card*" / "device" / "gpu_busy_percent")
            found = statistics._find_gpu_path(pattern)
            self.assertIsNotNone(found)
            self.assertEqual(statistics.read_gpu_busy(found), 67)
            self.assertIsNone(statistics._find_gpu_path(str(Path(td) / "nope*")))
            self.assertIsNone(statistics.read_gpu_busy(str(Path(td) / "gone")))

    def test_gpu_sample_returns_value_or_dash(self):
        out = statistics._sample_gpu()
        self.assertTrue(out == "-" or out.endswith("%"))


class TestBarRow(_StatsCase):
    def test_bar_contains_all_segments(self):
        statistics.bind({"stats": "on", "context_window": 8192})
        statistics.note_context([{"role": "user", "content": "x" * 4000}])
        statistics.begin_answer()
        statistics.end_answer()
        text = statistics._bar_text()
        for seg in ("LLM ", "t/s", "ctx ", "8k", "GPU ", "CPU ", "RAM "):
            self.assertIn(seg, text)
        self.assertNotIn("LLM -", text)

    def test_status_row_none_when_disabled(self):
        statistics.bind({"stats": "off"})
        self.assertIsNone(statistics.status_row())

    def test_clip_keeps_row_from_wrapping(self):
        self.assertEqual(statistics._clip("abcdefghij", 5), "abcd")
        self.assertEqual(statistics._clip("abc", 10), "abc")


class TestBarActivation(_StatsCase):
    def _mock_tty(self):
        out = MagicMock()
        out.isatty.return_value = True
        stdin = MagicMock()
        stdin.isatty.return_value = False  # sin consulta de cursor (no \033[6n)
        return out, stdin

    def test_activate_pins_bar_and_deactivate_restores(self):
        statistics.bind({"stats": "on"})
        out, stdin = self._mock_tty()
        with patch("sys.stdout", out), patch("sys.stdin", stdin):
            self.assertFalse(statistics.is_active())
            statistics.idle_tick()  # activa
            self.assertTrue(statistics.is_active())
            blob = "".join(str(c.args[0]) for c in out.write.call_args_list)
            self.assertIn("\033[1;", blob)   # region de scroll (DECSTBM)
            self.assertIn("ctx", blob)       # contenido de la barra
            out.write.reset_mock()
            statistics.deactivate_bar()
            self.assertFalse(statistics.is_active())
            last = str(out.write.call_args_list[-1].args[0])
            self.assertIn("\033[r", last)    # scroll normal restaurado

    def test_idle_tick_does_not_activate_when_disabled(self):
        statistics.bind({"stats": "off"})
        out, stdin = self._mock_tty()
        with patch("sys.stdout", out), patch("sys.stdin", stdin):
            statistics.idle_tick()
            self.assertFalse(statistics.is_active())
        out.write.assert_not_called()


class TestRequestTracking(_StatsCase):
    def test_run_react_agent_records_timing_usage_and_stream_options(self):
        statistics.bind({"stats": "off"})  # nada de escritura en la terminal
        with FakeLLM([RESP], usage={"prompt_tokens": 77, "completion_tokens": 33},
                     delay=0.05) as llm:
            config = {
                "base_url": f"http://127.0.0.1:{llm.port}/v1",
                "max_iterations": 3, "timeout": 10,
                "thought": "off", "observation": "off", "debug": "off",
                "format": "text", "stats": "off", "language": "en",
            }
            statistics.begin_answer()
            answer = run_react_agent("hola", config, {})
            statistics.end_answer()

        self.assertEqual(answer, "OK")
        payload = llm.requests[0]
        self.assertTrue(payload.get("stream_options", {}).get("include_usage"))
        self.assertGreater(statistics.last_req_s(), 0)
        self.assertGreater(statistics.last_tps(), 0)
        self.assertEqual(statistics.last_completion_tokens(), 33)
        self.assertEqual(statistics.last_ctx(), 77)
        self.assertGreater(statistics.last_answer_s(), 0)


class TestStatusBarE2E(unittest.TestCase):
    def test_bar_visible_at_prompt(self):
        with ConfigGuard({"stats": "on", "language": "en"}), AgentPty() as term:
            out = term.read(2.5)
        self.assertIn("ctx ", out)
        self.assertIn("RAM ", out)
        self.assertIn("\x1b[1;", out)  # region de scroll activa

    def test_bar_hidden_when_disabled(self):
        with ConfigGuard({"stats": "off", "language": "en"}), AgentPty() as term:
            out = term.read(2.5)
        self.assertNotIn("ctx ", out)
        self.assertNotIn("RAM ", out)

    def test_bar_stays_visible_during_and_after_answer(self):
        resp = "Thought: ok.\n\nFinal Answer:\nHOLA-OK"
        with FakeLLM([resp]) as llm, \
             ConfigGuard({"stats": "on", "language": "en",
                          "base_url": f"http://127.0.0.1:{llm.port}/v1",
                          "max_iterations": 5, "timeout": 10,
                          "thought": "off", "observation": "off",
                          "debug": "off"}), \
             AgentPty() as term:
            first = term.read(2.0)
            self.assertIn("ctx ", first)
            term.send(b"hola\r")
            after = term.read(3.0)
        # la respuesta se imprime encima (scroll de la region) y la barra
        # se reescribe en vivo durante la peticion: sigue visible.
        self.assertIn("HOLA-OK", after)
        self.assertIn("ctx ", after)


class TestTranslationsParity(unittest.TestCase):
    def test_sections_have_identical_keys_in_both_languages(self):
        es = json.loads((PROJECT / "translations_es.json").read_text(encoding="utf-8"))
        en = json.loads((PROJECT / "translations_en.json").read_text(encoding="utf-8"))
        for section in ("ui", "menu", "tools", "parser"):
            self.assertEqual(set(es[section]), set(en[section]), section)


if __name__ == "__main__":
    unittest.main()
