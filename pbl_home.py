#!/usr/bin/env python3
"""Ubicacion de la carpeta de usuario de Pebble-Coder (~/.pbl).

Todos los modulos resuelven sus ficheros de configuracion aqui: el directorio
se elige en un solo sitio (`~/.pbl`, o `PEBBLE_HOME` para tests) y `bootstrap()`
lo crea desde `defaults/` si falta (sin sobrescribir ediciones del usuario).
"""
import os
import shutil
from pathlib import Path

_FLAT = ("config.json", "tools.json", "commands.json",
         "translations_es.json", "translations_en.json",
         "system_prompt.md", "system_prompt_xml.md",
         "system_prompt_hermes.md", "system_prompt_deepseek.md")


def home() -> Path:
    """Directorio de usuario: `PEBBLE_HOME` si existe, si no `~/.pbl`."""
    env = os.environ.get("PEBBLE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".pbl"


def defaults_dir() -> Path:
    """Plantillas que install.sh copia y bootstrap() usa como respaldo."""
    return Path(__file__).resolve().parent / "defaults"


def ensure_home() -> Path:
    """Crea `~/.pbl` y sus subdirectorios agents/skills si no existen."""
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    (h / "agents").mkdir(exist_ok=True)
    (h / "skills").mkdir(exist_ok=True)
    return h


def bootstrap() -> None:
    """Crea `~/.pbl` desde `defaults/` si falta config.json (no sobrescribe)."""
    h = ensure_home()
    src = defaults_dir()
    if not (src / "config.json").exists():
        return
    for f in _FLAT:
        p = src / f
        if p.exists() and not (h / f).exists():
            shutil.copy2(p, h / f)
    for sub in ("agents", "skills"):
        d = src / sub
        if d.is_dir() and not any((h / sub).iterdir()):
            shutil.copytree(d, h / sub, dirs_exist_ok=True)


def config_path() -> Path:
    return home() / "config.json"


def tools_path() -> Path:
    return home() / "tools.json"


def commands_path() -> Path:
    return home() / "commands.json"


def translations_path(lang: str) -> Path:
    return home() / f"translations_{lang}.json"


def system_prompt_path(name: str) -> Path:
    return home() / name


def agents_dir() -> Path:
    return home() / "agents"


def skills_dir() -> Path:
    return home() / "skills"
