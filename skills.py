#!/usr/bin/env python3
"""Skills: procedimientos reutilizables indexados desde `<skills_dir>/*.md`.

Una skill es un procedimiento (una secuencia de pasos/instrucciones) que se
anexa al system prompt cuando esta activa. Formato y complimiento identicos a
los agentes (frontmatter con `name` + `description`, cuerpo, <= 200 lineas):

    ---
    name: responsive-layout
    description: Como dejar un layout responsive sin romper nada
    ---

    1. ...
    2. ...

Acceso por agente:
- si hay un agente activo, solo son accesibles las skills listadas en su
  header `skills` (una lista separada por comas: `skills: a, b`)
- sin agente activo, todas las skills validas estan disponibles
"""
from pathlib import Path
from typing import Dict, List, Optional

from agents import active_agent, parse_frontmatter

_SCRIPT_DIR = Path(__file__).resolve().parent

SKILL_MAX_LINES = 200
_FM = "---"


class SkillInfo:
    """Resultado del analisis de un fichero de skill."""

    def __init__(self, path: Path, name: str = "", description: str = "",
                 body: str = "", valid: bool = False, reason: str = ""):
        self.path = path
        self.name = name
        self.description = description
        self.body = body
        self.valid = valid
        self.reason = reason  # no_header | missing_fields | too_long | empty_body | read_error


def resolve_dir(skills_dir: str) -> Path:
    """Resuelve `<skills_dir>` relativo al directorio del proyecto."""
    path = Path(skills_dir or ".pbl/skills")
    if not path.is_absolute():
        path = _SCRIPT_DIR / path
    return path


def parse_skill_file(path: Path) -> SkillInfo:
    """Analiza un .md y decide si es una skill compliente e indexable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return SkillInfo(path, reason="read_error")

    if len(text.splitlines()) > SKILL_MAX_LINES:
        return SkillInfo(path, reason="too_long")

    header, body = parse_frontmatter(text)
    if not header:
        return SkillInfo(path, reason="no_header")

    name = header.get("name", "").strip()
    description = header.get("description", "").strip()
    info = SkillInfo(path, name=name, description=description, body=body)
    if not name or not description:
        info.reason = "missing_fields"
    elif not body:
        info.reason = "empty_body"
    else:
        info.valid = True
    return info


def load_skills(directory: Path) -> List[SkillInfo]:
    """Indexa todos los `<directory>/*.md` (validos e invalidos)."""
    if not directory.is_dir():
        return []
    return [parse_skill_file(p) for p in sorted(directory.glob("*.md"))]


def allowed_names(config: Dict[str, object]) -> Optional[List[str]]:
    """None = todas disponibles (sin agente); lista = solo las del agente."""
    info = active_agent(config)
    return None if info is None else info.skills


def visible_skills(config: Dict[str, object]) -> List[SkillInfo]:
    """Skills validas accesibles segun el agente activo (regla 1) o todas (regla 2)."""
    allowed = allowed_names(config)
    infos = load_skills(resolve_dir(str(config.get("skills_dir") or ".pbl/skills")))
    return [i for i in infos if i.valid and (allowed is None or i.name in allowed)]


def enabled_names(config: Dict[str, object]) -> List[str]:
    """Nombres de skills activadas (config `skills`: lista o cadena con comas)."""
    value = config.get("skills")
    if value is None:
        return []
    if isinstance(value, str):
        return [n.strip() for n in value.split(",") if n.strip()]
    if isinstance(value, (list, tuple)):
        return [str(n).strip() for n in value if str(n).strip()]
    return []


def active_skills_prompt(config: Dict[str, object]) -> str:
    """Cuerpo concatenado de las skills activas y accesibles (o "")."""
    enabled = set(enabled_names(config))
    if not enabled:
        return ""
    parts: List[str] = []
    for info in visible_skills(config):
        if info.name in enabled:
            parts.append(f"## Skill: {info.name}\n{info.body}")
    return "\n\n".join(parts)
