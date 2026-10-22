#!/usr/bin/env python3
"""Ubicacion de la carpeta de usuario de Pebble-Coder (~/.pbl).

Todos los modulos resuelven sus ficheros de configuracion aqui: el directorio
se elige en un solo sitio (`~/.pbl`, o `PEBBLE_HOME` para tests) y `bootstrap()`
lo crea desde `defaults/` si falta (sin sobrescribir ediciones del usuario).
"""
import json
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
    sync_defaults()


def _merge_missing(target: dict, defaults: dict) -> bool:
    """Añade a target las claves de defaults que falten. True si cambio algo."""
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
    return changed


def _merge_commands(target: dict, defaults: dict) -> bool:
    """Fusiona el objeto 'commands' sin tocar los comandos ya definidos."""
    changed = False
    current = target.get("commands")
    if not isinstance(current, dict):
        current = {}
        target["commands"] = current
        changed = True
    for key, value in defaults.get("commands", {}).items():
        if key not in current:
            current[key] = value
            changed = True
    return changed


def _merge_translations(target: dict, defaults: dict) -> bool:
    """Fusiona seccion por seccion sin tocar las traducciones ya escritas."""
    changed = False
    for section, entries in defaults.items():
        if not isinstance(entries, dict):
            continue
        current = target.get(section)
        if not isinstance(current, dict):
            current = {}
            target[section] = current
            changed = True
        for key, value in entries.items():
            if key not in current:
                current[key] = value
                changed = True
    return changed


def _sync_json(src_path: Path, dst_path: Path, merge) -> None:
    """Aplica `merge` sobre el fichero de la home. Solo escribe si algo cambio."""
    if not src_path.exists() or not dst_path.exists():
        return
    try:
        defaults = json.loads(src_path.read_text(encoding="utf-8"))
        target = json.loads(dst_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(defaults, dict) or not isinstance(target, dict):
        return
    if not merge(target, defaults):
        return
    dst_path.write_text(json.dumps(target, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def sync_defaults() -> None:
    """Añade a los ficheros de ~/.pbl las claves nuevas de defaults/.

    Nunca sobrescribe un valor del usuario: solo rellena lo que falta. Es lo que
    hace que una instalacion previa reciba los comandos y las traducciones nuevas.
    """
    src = defaults_dir()
    if not src.is_dir():
        return
    home = ensure_home()
    _sync_json(src / "config.json", home / "config.json", _merge_missing)
    _sync_json(src / "commands.json", home / "commands.json", _merge_commands)
    for lang in ("es", "en"):
        _sync_json(src / f"translations_{lang}.json",
                   home / f"translations_{lang}.json", _merge_translations)


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
