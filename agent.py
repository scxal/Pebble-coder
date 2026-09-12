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


def is_enabled(config: Dict[str, Any], key: str, default: bool = False) -> bool:
    val = config.get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("on", "true", "yes", "1", "enabled")
    return bool(val)


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        print(f"Advertencia: No se encontro '{config_path}', usando configuracion por defecto.")
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

    if config.get("format") == "xml" and prompt_file == "system_prompt.md":
        if Path("system_prompt_xml.md").exists():
            prompt_file = "system_prompt_xml.md"

    path = Path(prompt_file)
    if not path.exists():
        print(f"Advertencia: Archivo de prompt '{prompt_file}' no encontrado.")
        return "You are a helpful ReAct assistant."

    with open(path, "r", encoding="utf-8") as f:
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
            f"No se pudo conectar con el endpoint LLM en {url}. "
            "Asegúrate de que Ollama o tu servidor local esté activo."
        )
    except requests.exceptions.Timeout:
        raise TimeoutError(f"El LLM tardó más de {timeout} segundos en responder (timeout).")
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Error HTTP del servidor LLM ({response.status_code}): {response.text}")
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Respuesta inesperada del servidor LLM: {exc}")


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
            f"No se pudo conectar con el endpoint LLM en {url}. "
            "Asegúrate de que Ollama o tu servidor local esté activo."
        )
    except requests.exceptions.Timeout:
        raise TimeoutError(f"El LLM tardó más de {timeout} segundos en responder (timeout).")
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Error HTTP del servidor LLM ({response.status_code}): {response.text}")
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Respuesta inesperada del servidor LLM: {exc}")


_SPECIAL_TOKEN_RE = re.compile(
    r"<\|channel\|?>\s*(?:thought|thinking|analysis)?[ \t]*\n?"
    r"|</?\s*(?:channel|thought|thinking|analysis)\s*\|?>"
    r"|<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>"
    r"|<\|[^<>|]{1,32}\|?>",
    re.IGNORECASE,
)


def _strip_special_tokens(text: str, hold_partial: bool = False) -> str:
    """Elimina tokens de chat filtrados como texto literal (Gemma/llama.cpp emiten
    a veces '<|channel>thought' dentro del stream de razonamiento).

    Con hold_partial=True se retiene temporalmente un final que podria ser el
    inicio de un token incompleto (llegara en el siguiente chunk).
    """
    cleaned = _SPECIAL_TOKEN_RE.sub("", text)
    if hold_partial:
        lt = cleaned.rfind("<")
        if lt != -1 and ">" not in cleaned[lt:]:
            cleaned = cleaned[:lt]
    return cleaned


def _is_degenerate_repetition(text: str, min_reps: int = 4) -> bool:
    """Detecta si el final del texto repite una y otra vez el mismo segmento corto
    (bucle degenerado del modelo, p. ej. 'thought\\nthought\\nthought...')."""
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
    """Retiene el final del texto si es un prefijo parcial de una palabra de canal
    ('thin' podria ser el inicio de 'thinking' de un token <|channel>thinking partido
    en varios chunks) para no imprimirlo en vivo antes de tiempo."""
    cut = max(text.rfind(" "), text.rfind("\n"))
    tail = text[cut + 1:]
    low = tail.lower()
    if low and any(w.startswith(low) for w in _CHANNEL_WORDS):
        return text[: cut + 1]
    return text


_HEADER_PREFIXES = ("action:", "final answer:", "observation:", "input:", "thought:")


def _clip_pending_header(text: str) -> str:
    """Recorta el final de 'text' si la ultima linea parece el inicio de una
    cabecera ReAct a medio escribir (por ejemplo 'Act' o 'final ans'), para no
    imprimirla en vivo antes de tiempo."""
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
    """Devuelve el texto del bloque de pensamiento acumulado hasta ahora (para
    imprimirlo en vivo), o None si aun no es imprimible."""
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
    """Consume la respuesta SSE del LLM y devuelve el texto completo.

    Si 'label' no es None, imprime en vivo el bloque de pensamiento del modelo
    (con 'label' como encabezado) a medida que llegan sus tokens.
    Devuelve (texto_completo, pensamiento_impreso_en_vivo) o (None, False) si el
    servidor no envio un stream SSE valido.
    """
    resp = post_stream_request(messages, config)

    fmt = (config.get("format", "text") or "text").lower().strip()
    raw_reasoning = ""
    raw_content = ""
    printed_text = ""      # texto ya mostrado en vivo (prefijo estable del razonamiento)
    header_shown = False
    saw_data = False
    reasoning_aborted = False  # no imprimir mas el canal de razonamiento
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

            # Razonamiento acumulado y saneado (los tokens de chat pueden llegar
            # partido en varios chunks; se re-sanea sobre todo el acumulado)
            reasoning = _strip_special_tokens(raw_reasoning, hold_partial=True)

            if r_content and raw_reasoning.strip() and not reasoning.strip():
                special_streak += 1
            else:
                special_streak = 0

            if label is not None and not reasoning_aborted:
                if re.search(r"(?:^|\n)\s*Thought\s*:", reasoning, re.IGNORECASE):
                    # El razonamiento es en realidad un bloque ReAct duplicado
                    reasoning_aborted = True
                elif _is_degenerate_repetition(reasoning):
                    # Bucle degenerado del modelo: dejar de imprimir
                    reasoning_aborted = True
                else:
                    safe = _clip_pending_channel_word(reasoning)
                    # Si el razonamiento filtra cabeceras ReAct (Action:,
                    # Final Answer:...), recortar: a partir de ahi no es "pensar"
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

            # El modelo se quedo escupiendo tokens especiales o repitiendo el
            # mismo segmento: cortar el stream en vez de esperar el timeout
            if special_streak >= 8 or _is_degenerate_repetition(reasoning[-200:] if reasoning else ""):
                degenerate_break = True
                break
    finally:
        resp.close()

    full = _strip_special_tokens(raw_content)
    reasoning_final = _strip_special_tokens(raw_reasoning)

    # Si el modelo solo emitio razonamiento, usarlo como respuesta SOLO si trae
    # una accion util del protocolo ReAct (Action:/Final Answer:). Si no, se
    # descarta para no contaminar el historial con basura.
    if not saw_content_channel and reasoning_final:
        if re.search(r"(?:^|\n)\s*(?:Action|Final\s*Answer)\s*:", reasoning_final, re.IGNORECASE):
            full = reasoning_final

    if label is not None and header_shown and printed_text:
        # Separar razonamiento mostrado de la respuesta final
        print()

    if label is not None and not has_reasoning_channel:
        # Razonamiento en formato ReAct dentro de 'content': imprimir al cierre
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
        # El servidor no envio SSE valido: senal para reintentar sin stream
        return None, header_shown
    # full puede quedar en "" (respuesta vacia) -> el loop ReAct pedira reformato
    return full, header_shown


def run_react_agent(user_input: str, config: Dict[str, Any], tools_config: Dict[str, Any]) -> str:
    system_prompt = load_system_prompt(config)
    format_type = config.get("format", "text").lower()
    max_iterations = int(config.get("max_iterations", 10))

    debug_mode = is_enabled(config, "debug", False)
    show_thought = debug_mode or is_enabled(config, "thought", False)
    show_observation = debug_mode or is_enabled(config, "observation", False)

    # Etiqueta que acompaña al pensamiento en vivo (solo si se muestra)
    thought_label = bold(green("[Pensamiento]"))

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    for iteration in range(1, max_iterations + 1):
        if debug_mode:
            print(f"\n--- [Iteracion {iteration}/{max_iterations}] ---")

        # Solicitar la respuesta en streaming. El pensamiento se imprime en vivo
        # solo si show_thought está activo.
        try:
            label = thought_label if show_thought else None
            raw_response, thought_streamed = stream_llm(messages, config, label=label)
        except Exception as exc:
            print(f"\n[Error de conexion LLM] {exc}")
            return f"Error al comunicarse con el modelo: {exc}"

        if raw_response is None:
            # El servidor no envió SSE (respondió JSON completo): reintentar en modo no-stream.
            raw_response = call_llm(messages, config)

        parsed = parse_llm_response(raw_response, format_type=format_type)

        # Caso 1: Final Answer
        if parsed.is_final:
            if show_thought and parsed.thought and not thought_streamed:
                print(f"\n{thought_label}\n{green(parsed.thought)}")
            if debug_mode:
                print(f"\n[Final Answer]\n{parsed.final_answer}")
            else:
                print(f"\n{bold('Asistente:')}\n{yellow(parsed.final_answer)}")
            return parsed.final_answer or ""

        # Caso 3: Parser Invalido
        if parsed.error:
            messages.append({
                "role": "user",
                "content":
                (
                    "FORMAT ERROR.\n"
                    "Reply using exactly:\n\n"
                    "Thought:\n"
                    "...\n\n"
                    "Action:\n"
                    "tool_name\n\n"
                    "Input:\n"
                    "arguments\n"
                )
            })
            continue

        action = parsed.action
        tool_input = parsed.tool_input or ""

        # Mostrar accion
        if debug_mode:
            print(f"[Action] {action}")
            print(f"[Input]  {tool_input}")
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

        # Caso 4: Herramienta inexistente o deshabilitada
        tool_cfg = tools_config.get(action)
        if not tool_cfg or not tool_cfg.get("enabled", True):
            print(red(f"[Error] La herramienta '{action}' no existe o esta deshabilitada."))
            return f"Terminado: Herramienta '{action}' inexistente o deshabilitada."

        # Ejecutar la herramienta
        try:
            observation = execute_tool(action, tool_input, tools_config)
        except Exception as exc:
            print(red(f"[Error Critico de Ejecucion] {exc}"))
            return f"Terminado por error critico: {exc}"

        # Mostrar observacion solo si esta activada
        if show_observation:
            if debug_mode:
                print(f"[Observation]\n{observation}")
            else:
                print(cyan(f"[Observacion]\n{observation}"))

        # Actualizar el historial ReAct para el LLM
        messages.append({"role": "assistant", "content": raw_response})

        if format_type == "xml":
            obs_payload = f"<observation>\n{observation}\n</observation>"
        else:
            obs_payload = f"Observation:\n{observation}"

        messages.append({"role": "user", "content": obs_payload})

    # Caso 2: Limite maximo de iteraciones alcanzado
    msg = f"Se alcanzo el limite maximo de iteraciones ({max_iterations}) sin llegar a Final Answer."
    print(f"\n{yellow('[Aviso]')} {msg}")
    return msg


def main():
    config = load_config("config.json")
    tools_file = config.get("tools_file", "tools.json")
    tools_config = load_tools_config(tools_file)

    enabled_tools = [name for name, cfg in tools_config.items() if cfg.get("enabled", True)]
    debug_mode = is_enabled(config, "debug", False)

    # Parse simple CLI args: -c "prompt" runs directly, bypassing TUI
    if len(sys.argv) >= 3 and sys.argv[1] in ("-c", "--command"):
        prompt = sys.argv[2]
        if debug_mode:
            print(f"Ejecutando tarea: {prompt}")
        run_react_agent(prompt, config, tools_config)
        return

    # Modo de ejecucion directa por argumentos CLI (sin flag)
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        if debug_mode:
            print(f"Ejecutando tarea: {prompt}")
        run_react_agent(prompt, config, tools_config)
        return

    # Modo consola interactiva
    print("=" * 60)
    print(green("  Agente ReAct Ligero para Modelos Locales"))
    print("=" * 60)
    print(f"Modelo      : {config.get('model')}")
    print(f"Endpoint    : {config.get('base_url')}")
    print(f"Formato     : {config.get('format', 'text')}")
    print(f"Debug       : {'on' if debug_mode else 'off'}")
    print(f"Thought     : {'on' if is_enabled(config, 'thought') else 'off'}")
    print(f"Observation : {'on' if is_enabled(config, 'observation') else 'off'}")
    print(f"Tools       : {', '.join(enabled_tools)}")
    print("Escribe 'exit' o 'quit' para salir.")
    print("-" * 60)

    while True:
        try:
            user_input = input("\nTú > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSaliendo...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Saliendo...")
            break

        run_react_agent(user_input, config, tools_config)


if __name__ == "__main__":
    main()
