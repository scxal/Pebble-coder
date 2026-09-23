#!/usr/bin/env python3
"""Motor de menu interactivo generico para Pebble-Coder.

Menu reutilizable en la terminal: flechas o numeros (1-9) para seleccionar,
Enter para editar/activar, q/Esc para salir. Tipos de item:

- "toggle": valor on/off que se alterna con Enter
- "choice": cicla entre los valores de `choices` con Enter
- "text":   pide un valor por teclado (con `validate(raw) -> valor` opcional)
- "action": ejecuta `on_action()` con Enter y cierra el menu

El motor es solo UI: el llamador posee los datos (etiquetas, valores,
callbacks). Pensado para /settings hoy y /skill, /agent, etc. manana.
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

try:
    import select
    import termios
    import tty

    _HAS_TTY = True
except ImportError:
    _HAS_TTY = False


# --- Colores ---
def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return c(text, "38;5;40")


def cyan(text: str) -> str:
    return c(text, "36")


def yellow(text: str) -> str:
    return c(text, "33;1")


def red(text: str) -> str:
    return c(text, "31;1")


def bold(text: str) -> str:
    return c(text, "1")


def dim(text: str) -> str:
    return c(text, "90")


# --- Traducciones (seccion "menu") ---
_SCRIPT_DIR = Path(__file__).resolve().parent
_lang = "es"
_t_es = {}
_translations = {}
_menu_t = {}


def load_translations() -> None:
    global _lang, _t_es, _translations, _menu_t
    try:
        cfg = json.loads((_SCRIPT_DIR / "config.json").read_text(encoding="utf-8"))
        _lang = (cfg.get("language") or "es") if cfg.get("language") in ("es", "en") else "es"
    except Exception:
        pass
    try:
        _t_es = json.loads((_SCRIPT_DIR / "translations_es.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        _t_es = {}
    try:
        _translations = json.loads((_SCRIPT_DIR / f"translations_{_lang}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        _translations = {}
    _menu_t = _translations.get("menu", {})


load_translations()


def t(key: str, **kwargs) -> str:
    val = _menu_t.get(key, _t_es.get("menu", {}).get(key, ""))
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return val


class MenuItem:
    """Fila del menu: etiqueta, tipo, valor actual y callbacks."""

    def __init__(
        self,
        label: str,
        kind: str = "text",
        value: Any = None,
        choices: Optional[List[Any]] = None,
        validate: Optional[Callable[[str], Any]] = None,
        on_change: Optional[Callable[[Any], None]] = None,
        on_action: Optional[Callable[[], None]] = None,
    ):
        self.label = label
        self.kind = kind
        self.value = value
        self.choices = choices if choices is not None else []
        self.validate = validate
        self.on_change = on_change
        self.on_action = on_action

    def is_on(self) -> bool:
        return str(self.value).strip().lower() in ("on", "true", "yes", "1")

    def value_text(self, plain: bool = False) -> str:
        if self.kind == "toggle":
            if plain:
                return "on" if self.is_on() else "off"
            return green("[on]") if self.is_on() else dim("[off]")
        return str(self.value)

    def flip(self) -> Any:
        self.value = "off" if self.is_on() else "on"
        return self.value

    def cycle(self) -> Any:
        if not self.choices:
            return self.value
        try:
            idx = self.choices.index(self.value)
        except ValueError:
            idx = -1
        self.value = self.choices[(idx + 1) % len(self.choices)]
        return self.value


_CANCELLED = object()
_INVALID = object()
_KEY_TIMEOUT = 0.05
# Bracketed paste: el terminal envuelve los pegados en \x1b[200~ ... \x1b[201~
# para que sus \n internos NO se interpreten como Enter.
_PASTE_END = b"\x1b[201~"
_PASTE_GAP_TIMEOUT = 0.5  # pausa maxima entre bytes de un mismo pegado
_PASTE_MAX = 1_000_000    # tope de seguridad del payload


def _read_utf8_char(fd: int) -> str:
    """Lee un caracter UTF-8 completo (1-4 bytes) del fd crudo.

    Los acentos (á, Á, ñ) llegan en varias lecturas de un byte: decodificar
    byte a byte los partia en dos caracteres de reemplazo. Los bytes de
    continuacion ya estan buffered del mismo tecleo.
    """
    try:
        data = os.read(fd, 1)
    except OSError:
        return ""
    if not data:
        return ""
    first = data[0]
    remaining = 0
    if 0xC2 <= first <= 0xDF:
        remaining = 1
    elif 0xE0 <= first <= 0xEF:
        remaining = 2
    elif 0xF0 <= first <= 0xF4:
        remaining = 3
    for _ in range(remaining):
        ready, _, _ = select.select([fd], [], [], _KEY_TIMEOUT)
        if not ready:
            break
        try:
            nxt = os.read(fd, 1)
        except OSError:
            break
        if not nxt:
            break
        data += nxt
    return data.decode("utf-8", errors="replace")


def _read_key(fd: int, quit_chars: tuple = ("q", "Q")) -> str:
    """Lee una tecla del fd crudo: up/down/left/right/home/end/delete, enter,
    quit/esc/backspace/tab o el caracter."""
    ch = _read_utf8_char(fd)
    if ch in ("", "\x04"):
        return "quit"
    if ch == "\x1b":
        pending, _, _ = select.select([fd], [], [], _KEY_TIMEOUT)
        if not pending:
            return "esc"
        if os.read(fd, 1).decode("utf-8", errors="replace") != "[":
            return "esc"
        # CSI: se leen los bytes de parametro (0x20-0x3F) hasta el final (>= 0x40),
        # p.ej. 'A' (up), 'D' (left), '3~' (delete), '1~' (home).
        seq = ""
        while True:
            pending, _, _ = select.select([fd], [], [], _KEY_TIMEOUT)
            if not pending:
                return "unknown"
            nxt = os.read(fd, 1).decode("utf-8", errors="replace")
            if not nxt:
                return "unknown"
            seq += nxt
            if nxt >= "@":
                break
        if seq == "A":
            return "up"
        if seq == "B":
            return "down"
        if seq == "C":
            return "right"
        if seq == "D":
            return "left"
        if seq in ("H", "1~", "7~"):
            return "home"
        if seq in ("F", "4~", "8~"):
            return "end"
        if seq == "3~":
            return "delete"
        if seq == "200~":
            return "paste"
        return "unknown"
    if ch in ("\r", "\n"):
        return "enter"
    if ch in quit_chars:
        return "quit"
    if ch == "\x7f":
        return "backspace"
    if ch == "\t":
        return "tab"
    return ch


def _read_paste(fd: int) -> str:
    """Lee el payload de un pegado bracketed hasta \\x1b[201~.

    Byte a byte para no consumir nada posterior al terminador; si no llega
    (terminal sin 2004) se devuelve lo acumulado tras _PASTE_GAP_TIMEOUT.
    CRLF/CR se normalizan a LF (el modo crudo no traduce \r).
    """
    buf = bytearray()
    while len(buf) < _PASTE_MAX:
        ready, _, _ = select.select([fd], [], [], _PASTE_GAP_TIMEOUT)
        if not ready:
            break
        b = os.read(fd, 1)
        if not b:
            break
        buf += b
        if bytes(buf[-len(_PASTE_END):]) == _PASTE_END:
            payload = bytes(buf[:-len(_PASTE_END)])
            return payload.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    # Sin terminador: descarta un posible terminador parcial al final.
    for k in range(len(_PASTE_END) - 1, 0, -1):
        if bytes(buf[-k:]) == _PASTE_END[:k]:
            buf = buf[:-k]
            break
    return bytes(buf).decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _edit_value(item: MenuItem) -> Any:
    """Pide un nuevo valor en modo canonico. Devuelve _CANCELLED o _INVALID si no hay cambio."""
    if _HAS_TTY:
        try:
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass
    sys.stdout.write("\033[?25h")
    sys.stdout.write(t("menu_edit_prompt").format(label=item.label))
    sys.stdout.flush()
    try:
        raw = input()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write("\r\033[2K\n")
        sys.stdout.flush()
        return _CANCELLED
    raw = raw.strip()
    if not raw:
        return _CANCELLED
    if item.validate:
        try:
            return item.validate(raw)
        except (ValueError, TypeError):
            return _INVALID
    return raw


def render_row(item: MenuItem, selected: bool, number: int) -> str:
    if item.kind == "action":
        if selected:
            return c(f" ❯ {number:>2}. {item.label}", "7")
        return f"   {number:>2}. {item.label}"
    if selected:
        return c(f" ❯ {number:>2}. {item.label}: {item.value_text(plain=True)}", "7")
    return f"   {number:>2}. {item.label}: {item.value_text()}"


def run_menu(title: str, items: List[MenuItem], hint: Optional[str] = None) -> None:
    """Muestra el menu interactivo hasta que el usuario sale con q/Esc.

    Los cambios se aplican al vuelo con on_change (on_action cierra el menu).
    """
    if not items:
        return

    if not _HAS_TTY or not sys.stdin.isatty():
        _run_menu_fallback(title, items, hint)
        return

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    sel = 0
    status = ""
    extra_lines = 0
    total = len(items) + 3  # titulo + hint + items + status

    def render(first: bool = False) -> None:
        nonlocal extra_lines
        lines = [bold(cyan(title)), dim(hint if hint is not None else t("menu_hint"))]
        for i, item in enumerate(items):
            lines.append(render_row(item, i == sel, i + 1))
        lines.append(status)
        if not first:
            sys.stdout.write(f"\033[{total + extra_lines}A\r")
        for ln in lines:
            sys.stdout.write("\033[K" + ln + "\n")
        sys.stdout.write("\033[K")
        sys.stdout.flush()
        extra_lines = 0

    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[?25l")
        render(first=True)
        while True:
            key = _read_key(fd)

            if key in ("quit", "esc"):
                break

            if key == "up":
                sel = (sel - 1) % len(items)
                status = ""
            elif key == "down":
                sel = (sel + 1) % len(items)
                status = ""
            elif key.isdigit() and key != "0" and int(key) <= len(items):
                sel = int(key) - 1
                status = ""
            elif key == "enter":
                item = items[sel]
                if item.kind == "toggle":
                    new_value = item.flip()
                    if item.on_change:
                        item.on_change(new_value)
                    status = green("✓ " + t("menu_value_updated").format(label=item.label, value=new_value))
                elif item.kind == "choice":
                    new_value = item.cycle()
                    if item.on_change:
                        item.on_change(new_value)
                    status = green("✓ " + t("menu_value_updated").format(label=item.label, value=new_value))
                elif item.kind == "action":
                    if item.on_action:
                        item.on_action()
                    return
                else:
                    # Editar en modo canonico (con eco) y volver a crudo despues.
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
                    try:
                        new_value = _edit_value(item)
                    finally:
                        tty.setcbreak(fd)
                        sys.stdout.write("\033[?25l")
                        sys.stdout.flush()
                    extra_lines += 1
                    if new_value is _CANCELLED:
                        status = dim(t("menu_edit_cancelled"))
                    elif new_value is _INVALID:
                        status = red(t("menu_invalid_value"))
                    else:
                        item.value = new_value
                        if item.on_change:
                            item.on_change(new_value)
                        status = green("✓ " + t("menu_value_updated").format(label=item.label, value=new_value))
            else:
                continue

            render()
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def confirm(title: str, yes_label: Optional[str] = None, no_label: Optional[str] = None) -> bool:
    """Pregunta si/no usando el menu. Devuelve True solo si el usuario elige Si.

    Esc, q o Ctrl+C deniegan (respuesta segura por defecto).
    """
    result = {"allowed": False}
    items = [
        MenuItem(yes_label or t("confirm_yes"), "action",
                 on_action=lambda: result.update(allowed=True)),
        MenuItem(no_label or t("confirm_no"), "action",
                 on_action=lambda: result.update(allowed=False)),
    ]
    run_menu(title, items, hint=t("menu_hint_confirm"))
    return result["allowed"]


_POPUP_MAX = 8
# Refresco de la barra de estado en reposo. DEBE superar cualquier timeout de
# lectura de los tests E2E (max 3.0s): AgentPty.read() solo corta tras N
# segundos de silencio, y un tick mas rapido lo mantendria en bucle.
_STATUS_TICK = 4.0


def _terminal_width() -> int:
    try:
        cols = os.get_terminal_size(sys.stdin.fileno()).columns
        if cols > 0:
            return cols
    except (OSError, ValueError):
        pass
    return 80


def _wrapped_rows(text: str, width: int) -> int:
    """Filas que ocupa `text` (con \\n explicitos) estimando el wrap por ancho.

    Con un solo tramo equivale a la formula previa de command_input
    (ceil((L+1)/width)), asi que el comportamiento sin pegados no cambia.
    """
    rows = 0
    for seg in text.split("\n"):
        rows += max(1, -(-(len(seg) + 1) // width))
    return rows


def command_input(prompt: str, commands: List[str], descriptions: Optional[List[str]] = None,
                  on_tick: Optional[Callable[[], None]] = None) -> str:
    """Linea de input con autocompletado de comandos.

    Al escribir '/' muestra la lista de comandos y filtra mientras se escribe.
    ↑/↓ eligen, Enter ejecuta el comando resaltado (o el texto tal cual si no
    hay lista), Tab completa, Esc abre/cierra la lista. Ctrl+C/Ctrl+D se
    propagan al llamador (salida del programa).

    `on_tick` (opcional) se invoca tras cada tecla y con un timeout en
    reposo: el llamador lo usa para refrescar su barra de estado (la barra
    es global, no una fila de este prompt, asi que aqui no se dibuja).

    Pegado multilinea: se activa bracketed paste (`\033[?2004h`), de modo
    que el terminal envuelve los pegados en `\x1b[200~ ... \x1b[201~` y el
    texto se INSERTA completo (saltos incluidos) en el buffer; solo una
    pulsacion real de Enter envia el prompt.
    """
    if not _HAS_TTY or not sys.stdin.isatty():
        return input(prompt)

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    desc_list = descriptions if descriptions is not None else [""] * len(commands)
    buffer = ""
    pos = 0  # posicion del cursor dentro de buffer (el bloque inverso la marca)
    sel = 0
    show_popup = True
    prev_rows = 0
    prev_popup = 0

    def matched() -> List[str]:
        if not buffer.startswith("/"):
            return []
        low = buffer.lower()
        return [c for c in commands if c.lower().startswith(low)]

    def redraw(first: bool = False) -> None:
        nonlocal prev_rows, prev_popup
        shown = matched()[:_POPUP_MAX] if show_popup else []
        width = _terminal_width()
        in_rows = _wrapped_rows(prompt + buffer, width)
        p_rows = in_rows + (len(shown) + 1 if shown else 0)

        if not first:
            sys.stdout.write(f"\033[{prev_rows}A\r")
            for _ in range(prev_rows):
                sys.stdout.write("\033[K\n")
            sys.stdout.write(f"\033[{prev_rows}A")
        else:
            sys.stdout.write("\033[?25l")

        before = buffer[:pos]
        at = buffer[pos] if pos < len(buffer) else " "
        after = buffer[pos + 1:]
        # Bloque en video inverso sobre el caracter en pos: marca donde cae lo
        # tecleado, porque el cursor real queda oculto durante el redraw.
        sys.stdout.write("\033[K" + prompt + before + c(at, "7") + after + "\n")
        for i, cmd in enumerate(shown):
            idx = commands.index(cmd)
            desc = desc_list[idx] if idx < len(desc_list) else ""
            row = cmd if not desc else f"{cmd} — {desc}"
            if i == sel:
                sys.stdout.write("\033[K" + c(" ❯ " + row, "7") + "\n")
            else:
                sys.stdout.write("\033[K   " + row + "\n")
        if shown:
            sys.stdout.write("\033[K" + dim(t("command_hint")) + "\n")
        sys.stdout.flush()
        prev_rows = p_rows
        prev_popup = len(shown) + 1 if shown else 0
        if on_tick is not None:
            on_tick()  # la barra global se refresca tras redibujar el prompt

    try:
        tty.setcbreak(fd)
        # Sin ICRNL: un \r literal (tecla Enter o dentro de un pegado) llega
        # tal cual; _read_key acepta \r y \n como Enter igualmente.
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.ICRNL | termios.INLCR | termios.IGNCR)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # Bracketed paste ON: los pegados vienen envueltos en 200~/201~.
        sys.stdout.write("\033[?2004h")
        sys.stdout.flush()
        redraw(first=True)
        while True:
            if on_tick is not None:
                ready, _, _ = select.select([fd], [], [], _STATUS_TICK)
                if not ready:
                    on_tick()
                    continue
            key = _read_key(fd, quit_chars=())

            if key == "quit":
                raise EOFError
            if key == "enter":
                if show_popup and buffer.startswith("/"):
                    options = matched()
                    if options:
                        buffer = options[min(sel, len(options) - 1)]
                break
            if key == "up":
                options = matched()
                if options and show_popup:
                    sel = (sel - 1) % len(options)
            elif key == "down":
                options = matched()
                if options and show_popup:
                    sel = (sel + 1) % len(options)
            elif key == "esc":
                show_popup = not show_popup
            elif key == "tab":
                options = matched()
                if options and show_popup:
                    buffer = options[min(sel, len(options) - 1)]
                    pos = len(buffer)
            elif key == "left":
                pos = max(0, pos - 1)
            elif key == "right":
                pos = min(len(buffer), pos + 1)
            elif key == "home":
                pos = 0
            elif key == "end":
                pos = len(buffer)
            elif key == "delete":
                if pos < len(buffer):
                    buffer = buffer[:pos] + buffer[pos + 1:]
            elif key == "backspace":
                if pos > 0:
                    buffer = buffer[:pos - 1] + buffer[pos:]
                    pos -= 1
                sel = 0
                show_popup = True
            elif key == "paste":
                # Pegado multilinea: se inserta entero; NO se envia.
                text = _read_paste(fd)
                if text:
                    buffer = buffer[:pos] + text + buffer[pos:]
                    pos += len(text)
                    sel = 0
                    show_popup = True
            elif len(key) == 1 and key >= " ":
                buffer = buffer[:pos] + key + buffer[pos:]
                pos += 1
                sel = 0
                show_popup = True
            else:
                continue

            options = matched()
            if sel >= len(options):
                sel = max(0, len(options) - 1)
            redraw()

        return buffer
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\033[?25h\033[?2004l")  # cursor visible + bracketed paste OFF
        if prev_popup:
            sys.stdout.write(f"\033[{prev_popup}A\r")
            for _ in range(prev_popup):
                sys.stdout.write("\033[K\n")
        sys.stdout.flush()


def _run_menu_fallback(title: str, items: List[MenuItem], hint: Optional[str] = None) -> None:
    """Fallback sin termios: seleccion numerica por linea."""
    print(yellow(t("menu_fallback_warning")))
    while True:
        print(f"\n{bold(cyan(title))}")
        for i, item in enumerate(items, 1):
            print(render_row(item, False, i))
        raw = input(t("menu_fallback_prompt").format(max=len(items))).strip().lower()
        if raw in ("", "q", "quit", "exit"):
            return
        if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
            continue
        item = items[int(raw) - 1]
        if item.kind == "toggle":
            new_value = item.flip()
            if item.on_change:
                item.on_change(new_value)
        elif item.kind == "choice":
            new_value = item.cycle()
            if item.on_change:
                item.on_change(new_value)
        elif item.kind == "action":
            if item.on_action:
                item.on_action()
            return
        else:
            new_value = _edit_value(item)
            if new_value not in (_CANCELLED, _INVALID):
                item.value = new_value
                if item.on_change:
                    item.on_change(new_value)
