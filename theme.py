#!/usr/bin/env python3
"""Tema de color central para Pebble-Coder.

Todos los modulos de UI (agent.py, menu.py, statistics.py) pintan a traves de
aqui: el tema se elige en un solo sitio (`config.json` clave `theme`, o la fila
Tema de /settings con aplicacion en caliente) y se degrada solo en terminales
sin soporte.

Roles: green, blue, cyan, yellow, red, bold, dim, reverse.
- Terminal sin color (TERM=dumb, NO_COLOR, o sin TTY): se conservan solo los
  atributos no cromaticos (bold/reverse); el color queda vacio.
- Terminal sin 256 colores: los codigos 256 se degradan a su equivalente de 16.
"""
import os
import sys
from typing import Dict, List

_THEMES: Dict[str, Dict[str, str]] = {
    # Fondo oscuro (el aspecto de siempre, sin cambios).
    "default": {
        "green": "38;5;40",
        "blue": "48;5;21;38;5;231",
        "cyan": "36",
        "yellow": "33;1",
        "red": "31;1",
        "bold": "1",
        "dim": "90",
        "reverse": "7",
    },
    # Fondo claro: colores basicos, oscuros, sin fondos saturados.
    "light": {
        "green": "32",
        "blue": "44;30",
        "cyan": "36",
        "yellow": "33",
        "red": "31",
        "bold": "1",
        "dim": "2",
        "reverse": "7",
    },
    # Sin color: solo negrita y video inverso para la seleccion.
    "mono": {
        "green": "",
        "blue": "",
        "cyan": "",
        "yellow": "",
        "red": "",
        "bold": "1",
        "dim": "",
        "reverse": "7",
    },
}

DEFAULT_THEME = "default"

# Degradacion 256 -> 16 colores (solo los codigos que usamos).
_DEGRADE_16 = {
    "38;5;40": "32",
    "48;5;21;38;5;231": "44;37",
}

_current = DEFAULT_THEME


def available_themes() -> List[str]:
    return list(_THEMES)


def set_theme(name: str) -> str:
    """Fija el tema activo; un nombre desconocido deja el actual intacto."""
    global _current
    if name in _THEMES:
        _current = name
    return _current


def current_theme() -> str:
    return _current


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    try:
        return bool(sys.stdout.isatty())
    except (ValueError, AttributeError):
        return False


def _supports_256() -> bool:
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    return "256" in os.environ.get("TERM", "")


def _code(role: str) -> str:
    code = _THEMES[_current].get(role, "")
    if not code:
        return ""
    if not _supports_color():
        return code if role in ("bold", "reverse") else ""
    if role != "reverse" and not _supports_256() and code in _DEGRADE_16:
        return _DEGRADE_16[code]
    return code


def c(text: str, code: str) -> str:
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"


def paint(role: str, text: str) -> str:
    return c(text, _code(role))


def green(text: str) -> str:
    return paint("green", text)


def blue(text: str) -> str:
    return paint("blue", text)


def cyan(text: str) -> str:
    return paint("cyan", text)


def yellow(text: str) -> str:
    return paint("yellow", text)


def red(text: str) -> str:
    return paint("red", text)


def bold(text: str) -> str:
    return paint("bold", text)


def dim(text: str) -> str:
    return paint("dim", text)


def reverse(text: str) -> str:
    return paint("reverse", text)
