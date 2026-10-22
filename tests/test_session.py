"""Tests de /new, /compact y del compactado automatico del contexto."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import agent
import pbl_home
from session import HISTORY_MAX_MESSAGES, Session
from tests.helpers import CONFIG, ConfigGuard, FakeLLM

SUMMARY = "RESUMEN: el usuario pide leer un fichero de notas."


def _session_with_turns(turns=2):
    sess = Session()
    for i in range(turns):
        sess.add(f"pregunta {i}", f"respuesta {i}")
    return sess


class TestSessionObject(unittest.TestCase):
    def test_clear_empties_history_and_counts_removed(self):
        sess = _session_with_turns()
        self.assertEqual(sess.clear(), 4)
        self.assertTrue(sess.is_empty())
        self.assertEqual(sess.history, [])

    def test_add_trims_to_the_memory_limit(self):
        sess = Session()
        for i in range(5):
            sess.add(f"pregunta {i}", f"respuesta {i}")
        self.assertEqual(len(sess.history), HISTORY_MAX_MESSAGES)
        self.assertEqual(sess.history[0]["content"], "pregunta 2")

    def test_transcript_renders_both_roles(self):
        sess = _session_with_turns(1)
        text = sess.transcript()
        self.assertIn("Usuario: pregunta 0", text)
        self.assertIn("Asistente: respuesta 0", text)

    def test_summarize_sends_system_and_transcript(self):
        sess = _session_with_turns(1)
        seen = {}

        def fake_llm(messages, config):
            seen["messages"] = messages
            return SUMMARY

        self.assertEqual(sess.summarize(fake_llm, {}), SUMMARY)
        self.assertEqual(seen["messages"][0]["role"], "system")
        self.assertEqual(seen["messages"][1]["role"], "user")
        self.assertIn("pregunta 0", seen["messages"][1]["content"])

    def test_replace_swaps_the_whole_context(self):
        sess = _session_with_turns()
        sess.replace([{"role": "user", "content": "resumen"}])
        self.assertEqual(sess.history, [{"role": "user", "content": "resumen"}])


class TestNewCommand(unittest.TestCase):
    def test_new_clears_the_context(self):
        sess = _session_with_turns()
        with redirect_stdout(io.StringIO()):
            tools_config, prompt = agent.cmd_new({}, {}, sess)
        self.assertEqual(sess.history, [])
        self.assertIsNone(prompt)
        self.assertEqual(tools_config, {})

    def test_new_keeps_agent_and_skills(self):
        config = {"agent": "frontend-developer", "skills": ["alpha"]}
        sess = _session_with_turns()
        with redirect_stdout(io.StringIO()):
            agent.cmd_new(config, {}, sess)
        self.assertEqual(config["agent"], "frontend-developer")
        self.assertEqual(config["skills"], ["alpha"])


class TestCompactCommand(unittest.TestCase):
    def test_compact_replaces_the_context_with_a_summary_pair(self):
        sess = _session_with_turns()
        with FakeLLM([SUMMARY]) as llm:
            config = {"base_url": f"http://127.0.0.1:{llm.port}/v1", "timeout": 10}
            with redirect_stdout(io.StringIO()):
                ok = agent.apply_compaction(sess, config)
        self.assertTrue(ok)
        self.assertEqual(len(sess.history), 2)
        self.assertEqual(sess.history[0]["role"], "user")
        self.assertEqual(sess.history[1]["role"], "assistant")
        self.assertIn(SUMMARY, sess.history[0]["content"])

    def test_compact_request_is_not_part_of_the_context(self):
        sess = _session_with_turns()
        with FakeLLM([SUMMARY]) as llm:
            config = {"base_url": f"http://127.0.0.1:{llm.port}/v1", "timeout": 10}
            with redirect_stdout(io.StringIO()):
                agent.apply_compaction(sess, config)
            self.assertEqual(llm.count, 1)
            self.assertEqual(llm.requests[0]["messages"][0]["role"], "system")
        # El intercambio compactado no se guarda como turno.
        self.assertEqual(len(sess.history), 2)

    def test_failed_compaction_keeps_the_context(self):
        sess = _session_with_turns()
        before = list(sess.history)
        config = {"base_url": "http://127.0.0.1:1/v1", "timeout": 2}
        with redirect_stdout(io.StringIO()):
            ok = agent.apply_compaction(sess, config)
        self.assertFalse(ok)
        self.assertEqual(sess.history, before)

    def test_compact_on_empty_context_makes_no_call(self):
        sess = Session()
        with FakeLLM([SUMMARY]) as llm:
            config = {"base_url": f"http://127.0.0.1:{llm.port}/v1", "timeout": 10}
            with redirect_stdout(io.StringIO()):
                tools_config, prompt = agent.cmd_compact(config, {}, sess)
            self.assertEqual(llm.count, 0)
        self.assertIsNone(prompt)
        self.assertTrue(sess.is_empty())


class TestAutocompact(unittest.TestCase):
    def _config(self, **extra):
        config = {"autocompact": "on", "autocompact_threshold": 85,
                  "context_window": 1000}
        config.update(extra)
        return config

    def test_triggers_at_the_threshold(self):
        self.assertTrue(agent.should_autocompact(self._config(), 850))
        self.assertTrue(agent.should_autocompact(self._config(), 999))

    def test_does_not_trigger_below_the_threshold(self):
        self.assertFalse(agent.should_autocompact(self._config(), 849))
        self.assertFalse(agent.should_autocompact(self._config(), 0))

    def test_switch_disables_it(self):
        self.assertFalse(agent.should_autocompact(self._config(autocompact="off"), 999))
        self.assertFalse(agent.should_autocompact(self._config(autocompact=False), 999))

    def test_threshold_is_clamped(self):
        self.assertEqual(agent.autocompact_threshold({}), 85)
        self.assertEqual(agent.autocompact_threshold({"autocompact_threshold": 0}), 1)
        self.assertEqual(agent.autocompact_threshold({"autocompact_threshold": 500}), 100)
        self.assertEqual(agent.autocompact_threshold({"autocompact_threshold": "x"}), 85)

    def test_invalid_window_never_triggers(self):
        self.assertFalse(agent.should_autocompact(self._config(context_window=0), 999))


class TestSyncDefaults(unittest.TestCase):
    def test_sync_adds_missing_keys_and_keeps_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.json").write_text(
                json.dumps({"model": "mio", "language": "es"}), encoding="utf-8")
            (home / "commands.json").write_text(
                json.dumps({"commands": {"/exit": "cmd_exit"}}), encoding="utf-8")
            (home / "translations_es.json").write_text(
                json.dumps({"ui": {"cmd_new": "mi traduccion"}}), encoding="utf-8")
            (home / "translations_en.json").write_text(
                json.dumps({"ui": {}}), encoding="utf-8")

            previous = os.environ.get("PEBBLE_HOME")
            os.environ["PEBBLE_HOME"] = str(home)
            try:
                pbl_home.sync_defaults()
            finally:
                if previous is None:
                    os.environ.pop("PEBBLE_HOME", None)
                else:
                    os.environ["PEBBLE_HOME"] = previous

            cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["model"], "mio")
            self.assertIn("autocompact", cfg)
            self.assertIn("autocompact_threshold", cfg)

            cmds = json.loads((home / "commands.json").read_text(encoding="utf-8"))["commands"]
            self.assertEqual(cmds["/exit"], "cmd_exit")
            self.assertIn("/new", cmds)
            self.assertIn("/compact", cmds)

            es = json.loads((home / "translations_es.json").read_text(encoding="utf-8"))["ui"]
            self.assertEqual(es["cmd_new"], "mi traduccion")
            self.assertIn("cmd_compact", es)

            en = json.loads((home / "translations_en.json").read_text(encoding="utf-8"))["ui"]
            self.assertIn("cmd_new", en)


class TestSettingsRows(unittest.TestCase):
    def test_autocompact_rows_exist_and_persist(self):
        with ConfigGuard():
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            items = agent.build_settings_items(config)
            labels = [item.label for item in items]
            self.assertIn(agent.t("label_autocompact"), labels)
            self.assertIn(agent.t("label_autocompact_threshold"), labels)

            toggle = items[labels.index(agent.t("label_autocompact"))]
            self.assertEqual(toggle.kind, "toggle")
            toggle.on_change("off")
            self.assertEqual(config["autocompact"], "off")

            threshold = items[labels.index(agent.t("label_autocompact_threshold"))]
            self.assertEqual(threshold.validate("50"), 50)
            with self.assertRaises(ValueError):
                threshold.validate("0")
            with self.assertRaises(ValueError):
                threshold.validate("101")

    def test_rows_are_appended_so_digits_do_not_move(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        items = agent.build_settings_items(config)
        labels = [item.label for item in items]
        self.assertEqual(labels[-2:], [agent.t("label_autocompact"),
                                      agent.t("label_autocompact_threshold")])


if __name__ == "__main__":
    unittest.main()
