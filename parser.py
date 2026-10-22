import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import pbl_home


# --- Translation loading ---
_lang = "es"
try:
    _cfg = json.loads(pbl_home.config_path().read_text(encoding="utf-8"))
    _lang = (_cfg.get("language") or "es") if _cfg.get("language") in ("es", "en") else "es"
except Exception:
    pass

_parser_es = {}
try:
    _parser_es = json.loads(pbl_home.translations_path("es").read_text(encoding="utf-8")).get("parser", {})
except FileNotFoundError:
    pass

_parser_translations = {}
try:
    _parser_translations = json.loads(pbl_home.translations_path(_lang).read_text(encoding="utf-8")).get("parser", {})
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
    arguments: Optional[dict] = None
    format_used: Optional[str] = None


def clean_markdown_delimiters(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) >= 4:
        cleaned = cleaned[2:-2].strip()
    elif cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    elif cleaned.endswith("**"):
        # La cabecera (p.ej. 'Final Answer:') ya consumio los '**' de apertura.
        cleaned = cleaned[:-2].strip()
    return cleaned


def _react_header(name: str) -> str:
    """Header in `Name:`, `**Name:**` or `[Name]` form."""
    return rf"(?:^|\n)\s*(?:\[\s*{name}\s*\]\s*:?|[*#\s]*{name}[*#\s]*:)"


def parse_text_format(text: str) -> ParseResult:
    final_match = re.search(
        _react_header(r"Final\s*Answer") + r"[*#\s]*(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if final_match:
        final_text = clean_markdown_delimiters(final_match.group(1).strip())
        thought_match = re.search(
            _react_header(r"Thought")
            + r"[*#\s]*(.*?)(?="
            + _react_header(r"(?:Action|Input|Observation|Final\s*Answer)")
            + r"|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        thought = clean_markdown_delimiters(thought_match.group(1).strip()) if thought_match else None
        return ParseResult(is_final=True, final_answer=final_text, thought=thought)

    thought_match = re.search(
        _react_header(r"Thought")
        + r"[*#\s]*(.*?)(?="
        + _react_header(r"(?:Action|Input|Observation|Final\s*Answer)")
        + r"|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    thought = clean_markdown_delimiters(thought_match.group(1).strip()) if thought_match else None

    action_match = re.search(
        _react_header(r"Action") + r"[*#\s]*([^\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if not action_match:
        return ParseResult(error=t("missing_action_or_final_answer"))

    action_raw = action_match.group(1).strip()
    action = clean_markdown_delimiters(action_raw)

    input_match = re.search(
        _react_header(r"Input")
        + r"[*#\s]*(.*?)(?="
        + _react_header(r"(?:Observation|Final\s*Answer)")
        + r"|$)",
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


# --- Hermes / Qwen and DeepSeek tool-call families ---

_FW_BAR = "\uff5c"  # FULLWIDTH VERTICAL LINE, used by DeepSeek special tokens
_FW_LOW = "\u2581"  # LOWER ONE EIGHTH BLOCK, the SentencePiece word boundary

_THINK_RE = re.compile(
    r"[<\uff1c]think[>\uff1e](.*?)[<\uff1c]/think[>\uff1e]",
    re.IGNORECASE | re.DOTALL,
)

_HERMES_CALL_RE = re.compile(
    r"[<\uff1c]tool_call[>\uff1e](.*?)[<\uff1c]/tool_call[>\uff1e]",
    re.IGNORECASE | re.DOTALL,
)


def _ds_tok(name: str) -> str:
    """Regex for a DeepSeek special token; accepts the fullwidth trained form and ASCII leaks."""
    core = ("[" + _FW_LOW + "_]").join(name.split("_"))
    return "<[" + _FW_BAR + "|]" + core + "[" + _FW_BAR + "|]>"


def _strip_think(text: str) -> Tuple[str, Optional[str]]:
    thinking = None

    def _replace(match: "re.Match") -> str:
        nonlocal thinking
        body = match.group(1).strip()
        if thinking is None and body:
            thinking = body
        return ""

    return _THINK_RE.sub(_replace, text).strip(), thinking


def _load_call_json(body: str) -> Optional[dict]:
    """Tolerant JSON loader for a tool call body: strips fences, tolerates trailing commas."""
    if not body:
        return None
    text = body.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fence and fence.group(1).strip().startswith("{"):
        text = fence.group(1).strip()
    text = text.strip().strip("`").strip()
    if not text.startswith("{"):
        return None
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def parse_hermes_format(text: str) -> ParseResult:
    cleaned, thinking = _strip_think(text)
    if not cleaned:
        return ParseResult(error=t("empty_response"), format_used="hermes")

    calls = _HERMES_CALL_RE.findall(cleaned)
    if not calls:
        return ParseResult(error=t("missing_action_or_final_answer"), format_used="hermes")

    body = calls[0]
    data = _load_call_json(body) or {}
    action = str(data.get("name") or data.get("tool") or "").strip()
    raw_args = data.get("arguments", data.get("parameters"))
    arguments = None
    if isinstance(raw_args, dict):
        arguments = raw_args
    elif isinstance(raw_args, str):
        arguments = _load_call_json(raw_args)

    if not action:
        name_match = re.search(r"[\"']name[\"']\s*:\s*[\"']([^\"']+)[\"']", body)
        if name_match:
            action = name_match.group(1).strip()
        args_match = re.search(r"[\"'](?:arguments|parameters)[\"']\s*:\s*(\{.*\})", body, re.DOTALL)
        if args_match and arguments is None:
            arguments = _load_call_json(args_match.group(1))

    if not action:
        return ParseResult(error=t("missing_action_or_final_answer"), format_used="hermes")

    tool_input = json.dumps(arguments, ensure_ascii=False) if arguments is not None else body.strip()
    return ParseResult(
        thought=thinking,
        action=action,
        tool_input=tool_input,
        arguments=arguments,
        format_used="hermes",
    )


def parse_deepseek_format(text: str) -> ParseResult:
    cleaned, thinking = _strip_think(text)
    if not cleaned:
        return ParseResult(error=t("empty_response"), format_used="deepseek")

    action = None
    arguments = None
    tool_input = ""

    batch_match = re.search(
        _ds_tok("tool_calls_begin") + r"\s*(.*?)\s*" + _ds_tok("tool_calls_end"),
        cleaned,
        re.DOTALL,
    )
    if batch_match:
        call_match = re.search(
            _ds_tok("tool_call_begin") + r"(.*?)" + _ds_tok("tool_call_end"),
            batch_match.group(1),
            re.DOTALL,
        )
        if call_match:
            body = call_match.group(1).strip()
            sep_match = re.search(_ds_tok("tool_sep"), body)
            if sep_match:
                name_part = body[: sep_match.start()].strip()
                args_part = body[sep_match.end():].strip()
                if name_part.lower() == "function":
                    # Legacy R1 / V3-0324: name on the first line, arguments in a fenced JSON block.
                    lines = args_part.split("\n", 1)
                    action = lines[0].strip()
                    data = _load_call_json(lines[1]) if len(lines) > 1 else None
                    arguments = data
                    tool_input = json.dumps(data, ensure_ascii=False) if data is not None else (
                        lines[1].strip() if len(lines) > 1 else "")
                else:
                    action = name_part
                    data = _load_call_json(args_part)
                    arguments = data
                    tool_input = json.dumps(data, ensure_ascii=False) if data is not None else args_part
            else:
                action = body.split("\n", 1)[0].strip()

    if not action:
        invoke_match = re.search(
            r"<[" + _FW_BAR + r"|]\s*DSML[" + _FW_BAR + r"|]\s*invoke\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
            r"</[" + _FW_BAR + r"|]\s*DSML[" + _FW_BAR + r"|]\s*invoke[^>]*>",
            cleaned,
            re.IGNORECASE | re.DOTALL,
        )
        if invoke_match:
            action = invoke_match.group(1).strip()
            params = {}
            for param_match in re.finditer(
                r"<[" + _FW_BAR + r"|]\s*DSML[" + _FW_BAR + r"|]\s*parameter\s+name=[\"']([^\"']+)[\"']([^>]*)>"
                r"(.*?)</[" + _FW_BAR + r"|]\s*DSML[" + _FW_BAR + r"|]\s*parameter[^>]*>",
                invoke_match.group(2),
                re.IGNORECASE | re.DOTALL,
            ):
                attrs = param_match.group(2)
                value = param_match.group(3)
                if re.search(r"string\s*=\s*[\"']false[\"']", attrs, re.IGNORECASE):
                    try:
                        value = json.loads(value.strip())
                    except Exception:
                        value = value.strip()
                params[param_match.group(1)] = value
            arguments = params or None
            tool_input = json.dumps(params, ensure_ascii=False) if params else ""

    if not action:
        return ParseResult(error=t("missing_action_or_final_answer"), format_used="deepseek")

    return ParseResult(
        thought=thinking,
        action=action,
        tool_input=tool_input,
        arguments=arguments,
        format_used="deepseek",
    )


_PARSE_CHAINS = {
    "text": ["text", "xml", "hermes", "deepseek"],
    "xml": ["xml", "text", "hermes", "deepseek"],
    "hermes": ["hermes", "deepseek", "xml", "text"],
    "deepseek": ["deepseek", "hermes", "xml", "text"],
    "auto": ["hermes", "deepseek", "xml", "text"],
}

_PARSERS = {
    "text": parse_text_format,
    "xml": parse_xml_format,
    "hermes": parse_hermes_format,
    "deepseek": parse_deepseek_format,
}


def parse_llm_response(text: str, format_type: str = "text") -> ParseResult:
    text = (text or "").strip()
    if not text:
        return ParseResult(error=t("empty_response"))

    format_type = (format_type or "text").lower().strip()
    chain = _PARSE_CHAINS.get(format_type, ["text", "xml", "hermes", "deepseek"])

    first_error = None
    for name in chain:
        res = _PARSERS[name](text)
        if res.error:
            if first_error is None:
                first_error = res
            continue
        return res

    return first_error if first_error is not None else ParseResult(error=t("missing_action_or_final_answer"))
