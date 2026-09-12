#!/usr/bin/env python3
import json
import os
import readline
import re
import sys
from pathlib import Path
from typing import Dict, Any, List

import requests


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return c(text, "38;5;40")


def blue(text: str) -> str:
    return c(text, "48;5;21;38;5;231")


def cyan(text: str) -> str:
    return c(text, "36")


def yellow(text: str) -> str:
    return c(text, "33;1")


def red(text: str) -> str:
    return c(text, "31;1")


def bold(text: str) -> str:
    return c(text, "1")


from parser import parse_llm_response, ParseResult
from tools import execute_tool, load_tools_config, parse_write_file_args


# --- Translation loading ---
_SCRIPT_DIR = Path(__file__).resolve().parent
_lang = "es"
try:
    _cfg = json.loads((_SCRIPT_DIR / "config.json").read_text())
    _lang = (_cfg.get("language") or "es") if _cfg.get("language") in ("es", "en") else "es"
except Exception:
    pass

_t_es = {}
try:
    _t_es = json.loads((_SCRIPT_DIR / "translations_es.json").read_text())
except FileNotFoundError:
    pass

_translations = {}
try:
    _translations = json.loads((_SCRIPT_DIR / f"translations_{_lang}.json").read_text())
except FileNotFoundError:
    _translations = {}

_ui = _translations.get("ui", {})
_parser = _translations.get("parser", {})


def t(key: str, **kwargs) -> str:
    val = _ui.get(key, _t_es.get("ui", {}).get(key, ""))
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return val


def is_enabled(config: Dict[str, Any], key: str, default: bool = False) -> bool:
    val = config.get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("on", "true", "yes", "1", "enabled")
    return bool(val)


def confirm_execution(action: str, preview: str) -> bool:
    """Pide confirmacion al usuario para acciones sensibles; True si se permite."""
    print(yellow(t("tool_confirm_header").format(action=action)))
    print(f"  {preview}")
    ans = input(t("tool_confirm_yn")).strip().lower()
    return ans in ("y", "yes", "s", "si", "sí", "allow", "permitir", "1", "true", "", "on")


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        print(t("config_missing_warning").format(path=config_path))
        return {
            "model": "gemma4:e4b",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "temperature": 0.2,
            "max_iterations": 10,
            "timeout": 30,
            "format": "text",
            "debug": "off",
            "thought": "off",
            "observation": "off",
            "system_prompt_file": "system_prompt.md",
            "tools_file": "tools.json",
        }

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_system_prompt(config: Dict[str, Any]) -> str:
    prompt_file = config.get("system_prompt_file", "system_prompt.md")
    prompt_path = Path(prompt_file)
    if not prompt_path.is_absolute():
        prompt_path = _SCRIPT_DIR / prompt_path

    if config.get("format") == "xml" and prompt_file == "system_prompt.md":
        xml_candidate = _SCRIPT_DIR / "system_prompt_xml.md"
        if xml_candidate.exists():
            prompt_path = xml_candidate

    if not prompt_path.exists():
        print(t("prompt_missing_warning").format(path=prompt_file))
        return "You are a helpful ReAct assistant."

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def call_llm(messages: List[Dict[str, str]], config: Dict[str, Any]) -> str:
    base_url = config.get("base_url", "http://localhost:11434/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.get('api_key', 'ollama')}",
    }

    payload = {
        "model": config.get("model", "gemma4:e4b"),
        "messages": messages,
        "temperature": config.get("temperature", 0.2),
        "stream": False,
    }

    timeout = config.get("timeout", 30)

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return _strip_special_tokens(data["choices"][0]["message"]["content"])
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            t("connection_error_detail").format(url=url)
        )
    except requests.exceptions.Timeout:
        raise TimeoutError(
            t("timeout_error_detail").format(seconds=timeout)
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(
            t("http_error").format(code=response.status_code, response=response.text)
        )
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            t("unexpected_response").format(exc=exc)
        )


def post_stream_request(messages: List[Dict[str, str]], config: Dict[str, Any]) -> requests.Response:
    """Inicia una peticion SSE (stream=True) y devuelve la respuesta abierta."""
    base_url = config.get("base_url", "http://localhost:11434/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.get('api_key', 'ollama')}",
    }

    payload = {
        "model": config.get("model", "gemma4:e4b"),
        "messages": messages,
        "temperature": config.get("temperature", 0.2),
        "stream": True,
    }

    timeout = config.get("timeout", 30)

    try:
        # Forzar UTF-8: requests decodifica SSE (text/event-stream) como ISO-8859-1
        # si el servidor no declara charset, lo que rompe acentos (á, ó, ñ).
        response = requests.post(url, json=payload, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            t("connection_error_detail").format(url=url)
        )
    except requests.exceptions.Timeout:
        raise TimeoutError(
            t("timeout_error_detail").format(seconds=timeout)
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(
            t("http_error").format(code=response.status_code, response=response.text)
        )
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            t("unexpected_response").format(exc=exc)
        )


_SPECIAL_TOKEN_RE = re.compile(
    r"<\|channel\|?>\s*(?:thought|thinking|analysis)?[ \t]*\n?"
    r"|</?\s*(?:channel|thought|thinking|analysis)\s*\|?>"
    r"|<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>"
    r"|<\|[^<>|]{1,32}\|?>",
    re.IGNORECASE,
)


def _strip_special_tokens(text: str, hold_partial: bool = False) -> str:
    cleaned = _SPECIAL_TOKEN_RE.sub("", text)
    if hold_partial:
        lt = cleaned.rfind("<")
        if lt != -1 and ">" not in cleaned[lt:]:
            cleaned = cleaned[:lt]
    return cleaned


def _is_degenerate_repetition(text: str, min_reps: int = 4) -> bool:
    tail = text[-200:]
    for unit in range(1, 24):
        seg = tail[-unit:]
        if not seg.strip():
            continue
        count = 0
        pos = len(tail)
        while pos >= unit and tail[pos - unit:pos] == seg:
            count += 1
            pos -= unit
        if count >= min_reps:
            return True
    return False


_CHANNEL_WORDS = ("thought", "thinking", "analysis")


def _clip_pending_channel_word(text: str) -> str:
    cut = max(text.rfind(" "), text.rfind("\n"))
    tail = text[cut + 1:]
    low = tail.lower()
    if low and any(w.startswith(low) for w in _CHANNEL_WORDS):
        return text[: cut + 1]
    return text


_HEADER_PREFIXES = ("action:", "final answer:", "observation:", "input:", "thought:")


def _clip_pending_header(text: str) -> str:
    nl = text.rfind("\n")
    line_start = nl + 1 if nl != -1 else 0
    line = text[line_start:]
    probe = re.sub(r"^[\s*#_`]+", "", line).lower()
    if not probe:
        return text
    if any(h.startswith(probe) for h in _HEADER_PREFIXES):
        return text[:line_start]
    return text


def live_thought_text(full: str, fmt: str):
    if fmt == "xml":
        m = re.search(r"<thought>(.*?)</thought>", full, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    m = re.search(r"(?:^|\n)\s*[*#\s]*Thought\s*:[*#\s]*", full, re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    rest = full[start:]
    hdr = re.search(
        r"(?:^|\n)\s*[*#\s]*(?:Action|Final\s+Answer|Observation|Input|Thought)\s*:",
        rest,
        re.IGNORECASE,
    )
    if hdr:
        return rest[: hdr.start()].strip() or None
    safe = _clip_pending_header(rest)
    return safe.strip() or None


def stream_llm(messages: List[Dict[str, str]], config: Dict[str, Any], label=None):
    resp = post_stream_request(messages, config)

    fmt = (config.get("format", "text") or "text").lower().strip()
    raw_reasoning = ""
    raw_content = ""
    printed_text = ""
    header_shown = False
    saw_data = False
    reasoning_aborted = False
    special_streak = 0
    degenerate_break = False
    has_reasoning_channel = False
    saw_content_channel = False

    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.strip()
            if not line.startswith("data:"):
                continue
            saw_data = True
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                delta = (obj.get("choices") or [{}])[0].get("delta", {})
                r_content = delta.get("reasoning_content") or ""
                content = delta.get("content") or ""
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
                continue

            if r_content:
                has_reasoning_channel = True
                raw_reasoning += r_content

            if content:
                saw_content_channel = True
                raw_content += content

            reasoning = _strip_special_tokens(raw_reasoning, hold_partial=True)

            if r_content and raw_reasoning.strip() and not reasoning.strip():
                special_streak += 1
            else:
                special_streak = 0

            if label is not None and not reasoning_aborted:
                if re.search(r"(?:^|\n)\s*Thought\s*:", reasoning, re.IGNORECASE):
                    reasoning_aborted = True
                elif _is_degenerate_repetition(reasoning):
                    reasoning_aborted = True
                else:
                    safe = _clip_pending_channel_word(reasoning)
                    hdr = re.search(
                        r"(?:^|\n)\s*[*#\s]*(?:Action|Final\s+Answer|Input|Observation)\s*:",
                        safe,
                        re.IGNORECASE,
                    )
                    if hdr:
                        safe = safe[: hdr.start()]
                        reasoning_aborted = True
                    else:
                        safe = _clip_pending_header(safe)
                        safe = _clip_pending_channel_word(safe)
                    if safe.startswith(printed_text) and len(safe) > len(printed_text):
                        if not header_shown:
                            print(label, flush=True)
                            header_shown = True
                        sys.stdout.write(safe[len(printed_text):])
                        sys.stdout.flush()
                        printed_text = safe

            if special_streak >= 8 or _is_degenerate_repetition(reasoning[-200:] if reasoning else ""):
                degenerate_break = True
                break
    finally:
        resp.close()

    full = _strip_special_tokens(raw_content)
    reasoning_final = _strip_special_tokens(raw_reasoning)

    if not saw_content_channel and reasoning_final:
        if re.search(r"(?:^|\n)\s*(?:Action|Final\s*Answer)\s*:", reasoning_final, re.IGNORECASE):
            full = reasoning_final

    if label is not None and header_shown and printed_text:
        print()

    if label is not None and not has_reasoning_channel:
        text = live_thought_text(full, fmt)
        if text is not None:
            if not header_shown:
                print(label, flush=True)
                header_shown = True
            sys.stdout.write(text)
            sys.stdout.flush()
            printed_text = text
        if header_shown and printed_text:
            print()

    if not saw_data and not degenerate_break:
        return None, header_shown
    return full, header_shown


def confirm_execution(action: str, preview: str) -> bool:
    """Pide confirmacion al usuario antes de ejecutar acciones sensibles."""
    print(yellow(t("tool_confirm_header").format(action=action)))
    print(f"  {preview}")
    answer = input(t("tool_confirm_yn")).strip().lower()
    return answer in ("", "y", "yes", "s", "si", "sí", "1", "allow", "permitir", "permitido")


def run_react_agent(user_input: str, config: Dict[str, Any], tools_config: Dict[str, Any]) -> str:
    system_prompt = load_system_prompt(config)
    format_type = config.get("format", "text").lower()
    max_iterations = int(config.get("max_iterations", 10))

    debug_mode = is_enabled(config, "debug", False)
    show_thought = debug_mode or is_enabled(config, "thought", False)
    show_observation = debug_mode or is_enabled(config, "observation", False)

    thought_label = bold(green(t("thought_label")))

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    for iteration in range(1, max_iterations + 1):
        if debug_mode:
            print(t("debug_iteration").format(n=iteration, m=max_iterations))

        try:
            label = thought_label if show_thought else None
            raw_response, thought_streamed = stream_llm(messages, config, label=label)
        except Exception as exc:
            print(t('llm_connection_error').format(exc=exc))
            return t('communication_error').format(exc=exc)

        if raw_response is None:
            raw_response = call_llm(messages, config)

        parsed = parse_llm_response(raw_response, format_type=format_type)

        if parsed.is_final:
            if show_thought and parsed.thought and not thought_streamed:
                print(f"\n{thought_label}\n{green(parsed.thought)}")
            if debug_mode:
                print(t("debug_action"))
                print(parsed.final_answer)
            else:
                print(f"\n{bold(t('final_answer_label'))}\n{yellow(parsed.final_answer)}")
            return parsed.final_answer or ""

        if parsed.error:
            messages.append({
                "role": "user",
                "content": t("format_error_instructions"),
            })
            continue

        action = parsed.action
        tool_input = parsed.tool_input or ""

        if debug_mode:
            print(f"{t('debug_action')} {action}")
            print(f"{t('debug_input')}  {tool_input}")
        else:
            if action == "read_file":
                print(green(f"  {blue('read_file')} {tool_input}"))
            elif action == "write_file":
                path, _ = parse_write_file_args(tool_input)
                print(green(f"  {blue('write_file')} {path or tool_input}"))
            elif action == "web_search":
                print(green(f"  {blue('web_search')} {tool_input}"))
            elif action == "run_command":
                print(green(f"  {blue('run_command')} {tool_input}"))
            else:
                print(green(f"  {blue(action)} {tool_input}"))

        tool_cfg = tools_config.get(action)
        if not tool_cfg or not tool_cfg.get("enabled", True):
            print(red(t('tool_disabled_error').format(action=action)))
            return t('tool_disabled_terminated').format(action=action)

        # Confirm sensitive actions before executing them
        observation = None
        if action in ("write_file", "run_command"):
            if action == "write_file":
                preview_path, _ = parse_write_file_args(tool_input)
                preview = preview_path or tool_input
            else:
                preview = tool_input
            if not confirm_execution(action, preview):
                observation = t('tool_denied_observation').format(action=action)
                print(red(observation))
            else:
                try:
                    observation = execute_tool(action, tool_input, tools_config)
                except Exception as exc:
                    print(red(t('critical_error').format(exc=exc)))
                    return t('critical_terminated').format(exc=exc)
        else:
            try:
                observation = execute_tool(action, tool_input, tools_config)
            except Exception as exc:
                print(red(t('critical_error').format(exc=exc)))
                return t('critical_terminated').format(exc=exc)

        if show_observation:
            if debug_mode:
                print(t('debug_observation').format(observation=observation))
            else:
                print(cyan(t('normal_observation').format(observation=observation)))

        messages.append({"role": "assistant", "content": raw_response})

        if format_type == "xml":
            obs_payload = f"<observation>\n{observation}\n</observation>"
        else:
            obs_payload = f"Observation:\n{observation}"

        messages.append({"role": "user", "content": obs_payload})

    msg = t("max_iterations_message").format(max=max_iterations)
    print(f"\n{yellow(t('max_iterations_warning'))} {msg}")
    return msg


def main():
    config = load_config(str(_SCRIPT_DIR / "config.json"))
    tools_file = config.get("tools_file", "tools.json")
    
    # Resolve relative paths for project files
    if not Path(tools_file).is_absolute():
        tools_file = str(_SCRIPT_DIR / tools_file)
    tools_config = load_tools_config(tools_file)

    enabled_tools = [name for name, cfg in tools_config.items() if cfg.get("enabled", True)]
    debug_mode = is_enabled(config, "debug", False)

    # ASCII banner for "PEBBLE-CODER" (5-row x 4-col block font)
    _FONT = {
        "P": ("███ ", "█  █", "███ ", "█   ", "█   "),
        "E": ("████", "█   ", "███ ", "█   ", "████"),
        "B": ("███ ", "█  █", "███ ", "█  █", "███ "),
        "L": ("█   ", "█   ", "█   ", "█   ", "████"),
        "C": (" ███", "█   ", "█   ", "█   ", " ███"),
        "O": (" ██ ", "█  █", "█  █", "█  █", " ██ "),
        "D": ("███ ", "█  █", "█  █", "█  █", "███ "),
        "R": ("███ ", "█  █", "███ ", "█ █ ", "█  █"),
        "-": ("    ", "    ", "████", "    ", "    "),
    }
    word = "PEBBLE-CODER"
    rows = [""] * 5
    for ch in word:
        glyph = _FONT.get(ch.upper(), ("    ",) * 5)
        for i in range(5):
            rows[i] += glyph[i] + " "
    print("\n" + "\n".join(rows))

    # Parse simple CLI args: -c "prompt" runs directly, bypassing TUI
    if len(sys.argv) >= 3 and sys.argv[1] in ("-c", "--command"):
        prompt = sys.argv[2]
        if debug_mode:
            print(t('cli_task_executing').format(prompt=prompt))
        run_react_agent(prompt, config, tools_config)
        return

    # Modo de ejecucion directa por argumentos CLI (sin flag)
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        if debug_mode:
            print(t('cli_task_executing').format(prompt=prompt))
        run_react_agent(prompt, config, tools_config)
        return

    # Info display (banner already printed above)
    print(f"Modelo      : {config.get('model')}")
    print(f"Endpoint    : {config.get('base_url')}")
    print(f"Formato     : {config.get('format', 'text')}")
    print(f"Debug       : {'on' if debug_mode else 'off'}")
    print(f"Thought     : {'on' if is_enabled(config, 'thought') else 'off'}")
    print(f"Observation : {'on' if is_enabled(config, 'observation') else 'off'}")
    print(f"Tools       : {', '.join(enabled_tools)}")
    print(t("exit_prompt"))
    print("-" * 60)

    while True:
        try:
            user_input = input(t("prompt")).strip()
        except (KeyboardInterrupt, EOFError):
            print(t("exit_message"))
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print(t("exit_message"))
            break

        run_react_agent(user_input, config, tools_config)


if __name__ == "__main__":
    main()
