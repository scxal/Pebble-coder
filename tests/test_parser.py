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


if __name__ == "__main__":
    unittest.main()
