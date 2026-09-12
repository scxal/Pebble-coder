import json
import re
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


# --- Translation loading ---
_SCRIPT_DIR = Path(__file__).resolve().parent
_lang = "es"
try:
    _cfg = json.loads((_SCRIPT_DIR / "config.json").read_text())
    _lang = (_cfg.get("language") or "es") if _cfg.get("language") in ("es", "en") else "es"
except Exception:
    pass

_parser_es = {}
try:
    _parser_es = json.loads((_SCRIPT_DIR / "translations_es.json").read_text()).get("parser", {})
except FileNotFoundError:
    pass

_parser_translations = {}
try:
    _parser_translations = json.loads((_SCRIPT_DIR / f"translations_{_lang}.json").read_text()).get("parser", {})
except FileNotFoundError:
    _parser_translations = {}


def t(key: str, **kwargs) -> str:
    val = _parser_translations.get(key, _parser_es.get(key, ""))
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return val


@dataclass
class ParseResult:
    is_final: bool = False
    thought: Optional[str] = None
    action: Optional[str] = None
    tool_input: Optional[str] = None
    final_answer: Optional[str] = None
    error: Optional[str] = None


def clean_markdown_delimiters(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) >= 4:
        cleaned = cleaned[2:-2].strip()
    elif cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def parse_text_format(text: str) -> ParseResult:
    final_match = re.search(
        r"(?:^|\n)\s*[*#\s]*Final\s*Answer[*#\s]*:[*#\s]*(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if final_match:
        final_text = clean_markdown_delimiters(final_match.group(1).strip())
        thought_match = re.search(
            r"(?:^|\n)\s*[*#\s]*Thought[*#\s]*:[*#\s]*(.*?)(?=\n\s*[*#\s]*(?:Action|Input|Observation|Final\s*Answer)[*#\s]*:|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        thought = clean_markdown_delimiters(thought_match.group(1).strip()) if thought_match else None
        return ParseResult(is_final=True, final_answer=final_text, thought=thought)

    thought_match = re.search(
        r"(?:^|\n)\s*[*#\s]*Thought[*#\s]*:[*#\s]*(.*?)(?=\n\s*[*#\s]*(?:Action|Input|Observation|Final\s*Answer)[*#\s]*:|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    thought = clean_markdown_delimiters(thought_match.group(1).strip()) if thought_match else None

    action_match = re.search(
        r"(?:^|\n)\s*[*#\s]*Action[*#\s]*:[*#\s]*([^\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if not action_match:
        return ParseResult(error=t("missing_action_or_final_answer"))

    action_raw = action_match.group(1).strip()
    action = clean_markdown_delimiters(action_raw)

    input_match = re.search(
        r"(?:^|\n)\s*[*#\s]*Input[*#\s]*:[*#\s]*(.*?)(?=\n\s*[*#\s]*Observation[*#\s]*:|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    tool_input_raw = input_match.group(1).strip() if input_match else ""
    tool_input = clean_markdown_delimiters(tool_input_raw)

    return ParseResult(
        is_final=False,
        thought=thought,
        action=action,
        tool_input=tool_input,
    )


def parse_xml_format(text: str) -> ParseResult:
    final_match = re.search(
        r"<final_answer>(.*?)(?:</final_answer>|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if final_match:
        thought_match = re.search(r"<thought>(.*?)</thought>", text, re.IGNORECASE | re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else None
        return ParseResult(
            is_final=True,
            final_answer=final_match.group(1).strip(),
            thought=thought,
        )

    thought_match = re.search(r"<thought>(.*?)</thought>", text, re.IGNORECASE | re.DOTALL)
    thought = thought_match.group(1).strip() if thought_match else None

    action_match = re.search(r"<action>(.*?)</action>", text, re.IGNORECASE | re.DOTALL)
    if not action_match:
        return ParseResult(error=t("missing_action_or_final_answer"))

    action = action_match.group(1).strip()

    input_match = re.search(r"<input>(.*?)</input>", text, re.IGNORECASE | re.DOTALL)
    tool_input = input_match.group(1).strip() if input_match else ""

    return ParseResult(
        is_final=False,
        thought=thought,
        action=action,
        tool_input=tool_input,
    )


def parse_llm_response(text: str, format_type: str = "text") -> ParseResult:
    text = (text or "").strip()
    if not text:
        return ParseResult(error=t("empty_response"))

    format_type = (format_type or "text").lower().strip()

    if format_type == "xml":
        res = parse_xml_format(text)
        if res.error and ("Action:" in text or "Final Answer:" in text):
            text_res = parse_text_format(text)
            if not text_res.error:
                return text_res
        return res
    else:
        res = parse_text_format(text)
        if res.error and ("<action>" in text or "<final_answer>" in text):
            xml_res = parse_xml_format(text)
            if not xml_res.error:
                return xml_res
        return res
