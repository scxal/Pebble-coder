"""Unit tests del parser ReAct (texto y XML). Sin red, sin terminal."""
import unittest

from parser import parse_llm_response


class TestTextFormat(unittest.TestCase):
    def test_action_and_input(self):
        r = parse_llm_response("Thought: necesito mirar\n\nAction: list_files\n\nInput: .")
        self.assertFalse(r.is_final)
        self.assertEqual(r.action, "list_files")
        self.assertEqual(r.tool_input, ".")
        self.assertIsNone(r.error)

    def test_multiline_input(self):
        r = parse_llm_response("Thought: t\n\nAction: write_file\n\nInput: notas.md\ncontenido largo")
        self.assertEqual(r.action, "write_file")
        self.assertEqual(r.tool_input, "notas.md\ncontenido largo")

    def test_final_answer(self):
        r = parse_llm_response("Thought: listo\n\nFinal Answer:\nTodo hecho")
        self.assertTrue(r.is_final)
        self.assertEqual(r.final_answer, "Todo hecho")

    def test_final_answer_multiline(self):
        r = parse_llm_response("Final Answer:\nlinea 1\nlinea 2")
        self.assertTrue(r.is_final)
        self.assertEqual(r.final_answer, "linea 1\nlinea 2")

    def test_markdown_wrapped_final(self):
        r = parse_llm_response("Final Answer: **resultado**")
        self.assertEqual(r.final_answer, "resultado")

    def test_case_insensitive_headers(self):
        r = parse_llm_response("thought: t\n\naction: read_file\n\ninput: agent.py")
        self.assertEqual(r.action, "read_file")

    def test_empty_response_is_error(self):
        r = parse_llm_response("")
        self.assertIsNotNone(r.error)
        self.assertFalse(r.is_final)

    def test_missing_action_is_error(self):
        r = parse_llm_response("Thought: solo pienso")
        self.assertIsNotNone(r.error)
        self.assertIn("Action", r.error)


class TestXmlFormat(unittest.TestCase):
    def test_action_and_input(self):
        r = parse_llm_response("<thought>t</thought>\n<action>read_file</action>\n<input>config.json</input>", format_type="xml")
        self.assertFalse(r.is_final)
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.tool_input, "config.json")

    def test_final_answer(self):
        r = parse_llm_response("<thought>t</thought>\n<final_answer>hecho</final_answer>", format_type="xml")
        self.assertTrue(r.is_final)
        self.assertEqual(r.final_answer, "hecho")

    def test_missing_action_is_error(self):
        r = parse_llm_response("<thought>solo pensamiento</thought>", format_type="xml")
        self.assertIsNotNone(r.error)


class TestHermesFormat(unittest.TestCase):
    SAMPLE = """<tool_call>
{
  "name": "run_python",
  "arguments": {
    "code": "print(1+1)"
  }
}
</tool_call>"""

    def test_sample_verbatim(self):
        r = parse_llm_response(self.SAMPLE, format_type="hermes")
        self.assertIsNone(r.error)
        self.assertFalse(r.is_final)
        self.assertEqual(r.action, "run_python")
        self.assertEqual(r.arguments, {"code": "print(1+1)"})

    def test_arguments_as_json_string(self):
        raw = '<tool_call>{"name": "read_file", "arguments": "{\\"path\\": \\"a.txt\\"}"}</tool_call>'
        r = parse_llm_response(raw, format_type="hermes")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.arguments, {"path": "a.txt"})

    def test_fenced_json_body(self):
        raw = '<tool_call>```json\n{"name": "list_files", "arguments": {"path": "."}}\n```</tool_call>'
        r = parse_llm_response(raw, format_type="hermes")
        self.assertEqual(r.action, "list_files")
        self.assertEqual(r.arguments, {"path": "."})

    def test_first_call_wins_on_parallel_batch(self):
        raw = (
            '<tool_call>{"name": "read_file", "arguments": {"path": "a"}}</tool_call>\n'
            '<tool_call>{"name": "read_file", "arguments": {"path": "b"}}</tool_call>'
        )
        r = parse_llm_response(raw, format_type="hermes")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.arguments, {"path": "a"})

    def test_think_span_is_extracted(self):
        raw = "<think>necesito mirar</think>\n" + self.SAMPLE
        r = parse_llm_response(raw, format_type="hermes")
        self.assertEqual(r.thought, "necesito mirar")
        self.assertEqual(r.action, "run_python")

    def test_final_answer_tag(self):
        r = parse_llm_response("<final_answer>listo</final_answer>", format_type="hermes")
        self.assertTrue(r.is_final)
        self.assertEqual(r.final_answer, "listo")

    def test_missing_call_is_error(self):
        r = parse_llm_response("solo texto sin llamada", format_type="hermes")
        self.assertIsNotNone(r.error)


class TestDeepSeekFormat(unittest.TestCase):
    SAMPLE = """<｜tool▁calls▁begin｜>

<｜tool▁call▁begin｜>
run_command
<｜tool▁sep｜>
{"command": "ls -la"}
<｜tool▁call▁end｜>

<｜tool▁calls▁end｜>"""

    DSML_OPEN = "<" + "｜DSML｜tool_calls>"
    DSML_CLOSE = "<" + "/｜DSML｜tool_calls>"
    INVOKE_OPEN = "<" + '｜DSML｜invoke name="get_weather">'
    INVOKE_CLOSE = "<" + "/｜DSML｜invoke>"
    PARAM_OPEN = "<" + "｜DSML｜parameter name="
    PARAM_CLOSE = "<" + "/｜DSML｜parameter>"

    def test_sample_verbatim(self):
        r = parse_llm_response(self.SAMPLE, format_type="deepseek")
        self.assertIsNone(r.error)
        self.assertEqual(r.action, "run_command")
        self.assertEqual(r.arguments, {"command": "ls -la"})

    def test_compact_v31(self):
        raw = ('<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>read_file<｜tool▁sep｜>'
               '{"path": "a.txt"}<｜tool▁call▁end｜><｜tool▁calls▁end｜>')
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.arguments, {"path": "a.txt"})

    def test_legacy_r1_fenced_body(self):
        raw = ('<｜tool▁calls▁begin｜>\n<｜tool▁call▁begin｜>\nfunction<｜tool▁sep｜>get_weather\n'
               '```json\n{"location": "Lima"}\n```\n<｜tool▁call▁end｜>\n<｜tool▁calls▁end｜>')
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.action, "get_weather")
        self.assertEqual(r.arguments, {"location": "Lima"})

    def test_ascii_leak_tolerated(self):
        raw = ('<|tool_calls_begin|><|tool_call_begin|>read_file<|tool_sep|>'
               '{"path": "x"}<|tool_call_end|><|tool_calls_end|>')
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.arguments, {"path": "x"})

    def test_dsml_envelope(self):
        location = self.PARAM_OPEN + '"location" string="true">Lima' + self.PARAM_CLOSE
        days = self.PARAM_OPEN + '"days" string="false">3' + self.PARAM_CLOSE
        raw = "\n".join([
            self.DSML_OPEN,
            self.INVOKE_OPEN,
            location,
            days,
            self.INVOKE_CLOSE,
            self.DSML_CLOSE,
        ])
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.action, "get_weather")
        self.assertEqual(r.arguments, {"location": "Lima", "days": 3})

    def test_think_span_is_extracted(self):
        raw = "<think>pensando</think>\n" + self.SAMPLE
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.thought, "pensando")
        self.assertEqual(r.action, "run_command")

    def test_first_call_wins_on_parallel_batch(self):
        raw = ('<｜tool▁calls▁begin｜>'
               '<｜tool▁call▁begin｜>read_file<｜tool▁sep｜>{"path": "a"}<｜tool▁call▁end｜>'
               '<｜tool▁call▁begin｜>read_file<｜tool▁sep｜>{"path": "b"}<｜tool▁call▁end｜>'
               '<｜tool▁calls▁end｜>')
        r = parse_llm_response(raw, format_type="deepseek")
        self.assertEqual(r.arguments, {"path": "a"})

    def test_missing_call_is_error(self):
        r = parse_llm_response("solo texto sin llamada", format_type="deepseek")
        self.assertIsNotNone(r.error)


class TestAutoChain(unittest.TestCase):
    def test_text_sample(self):
        r = parse_llm_response("Thought: t\n\nAction: read_file\n\nInput: a.py", format_type="auto")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.tool_input, "a.py")

    def test_hermes_sample(self):
        raw = '<tool_call>{"name": "list_files", "arguments": {"path": "."}}</tool_call>'
        r = parse_llm_response(raw, format_type="auto")
        self.assertEqual(r.action, "list_files")
        self.assertEqual(r.arguments, {"path": "."})
        self.assertEqual(r.format_used, "hermes")

    def test_deepseek_sample(self):
        raw = ('<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>read_file<｜tool▁sep｜>'
               '{"path": "a"}<｜tool▁call▁end｜><｜tool▁calls▁end｜>')
        r = parse_llm_response(raw, format_type="auto")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.format_used, "deepseek")

    def test_xml_sample(self):
        raw = "<thought>t</thought>\n<action>read_file</action>\n<input>a.py</input>"
        r = parse_llm_response(raw, format_type="auto")
        self.assertEqual(r.action, "read_file")

    def test_malformed_is_error(self):
        r = parse_llm_response("nada util", format_type="auto")
        self.assertIsNotNone(r.error)


class TestBracketHeaders(unittest.TestCase):
    def test_bracket_action_and_input(self):
        raw = "[Action] write_file\n[Input] notas.md\nlinea uno"
        r = parse_llm_response(raw, format_type="text")
        self.assertIsNone(r.error)
        self.assertEqual(r.action, "write_file")
        self.assertEqual(r.tool_input, "notas.md\nlinea uno")

    def test_bracket_final_answer(self):
        r = parse_llm_response("[Final Answer] listo", format_type="text")
        self.assertTrue(r.is_final)
        self.assertEqual(r.final_answer, "listo")

    def test_bracket_thought(self):
        raw = "[Thought] necesito mirar\n[Action] read_file\n[Input] a.py"
        r = parse_llm_response(raw, format_type="auto")
        self.assertEqual(r.action, "read_file")
        self.assertEqual(r.thought, "necesito mirar")


if __name__ == "__main__":
    unittest.main()
