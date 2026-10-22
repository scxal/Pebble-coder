#!/usr/bin/env python3
"""Agentes adicionales: prompts EXTRA indexados desde `<agents_dir>/*.md`.

Un agente NO sustituye al system prompt: es un prompt adicional que se anexa
al system prompt cuando el agente esta activo (el system prompt base sigue
siendo el minimo que ya habilita las herramientas).

Formato (frontmatter tipo estandar abierto: `name` + `description`):

    ---
    name: revisor
    description: Revisa codigo y senala bugs con brevedad
    ---

    Instrucciones adicionales del agente...

Complimiento (si falla, el agente NO se indexa y /agent lo ignora):
- el fichero debe empezar por `---` y cerrar el header con otro `---`
- `name` y `description` no pueden estar vacios
- el fichero completo no puede superar AGENT_MAX_LINES lineas
- el cuerpo (tras el header) no puede estar vacio
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pbl_home

AGENT_MAX_LINES = 200
_FM = "---"


class AgentInfo:
    """Resultado del analisis de un fichero de agente."""

    def __init__(self, path: Path, name: str = "", description: str = "",
                 body: str = "", valid: bool = False, reason: str = "",
                 skills: Optional[List[str]] = None):
        self.path = path
        self.name = name
        self.description = description
        self.body = body
        self.valid = valid
        self.reason = reason  # no_header | missing_fields | too_long | empty_body | read_error
        self.skills = skills or []  # nombres de skills accesibles (header `skills`)


def resolve_dir(agents_dir: str) -> Path:
    """Resuelve `<agents_dir>` relativo a ~/.pbl (o absoluto)."""
    path = Path(agents_dir or ".pbl/agents")
    if not path.is_absolute():
        path = pbl_home.home() / path
    return path


def parse_list(value: str) -> List[str]:
    """`a, b` o `[a, b]` -> ['a', 'b'] (tambien admite comas y comillas)."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [item.strip().strip('"').strip("'") for item in value.split(",")]
    return [item for item in items if item]


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Devuelve (header, body). Header vacio si no hay frontmatter valido."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM:
        return {}, ""
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM:
            header: Dict[str, str] = {}
            for row in lines[1:i]:
                if ":" not in row:
                    continue
                key, value = row.split(":", 1)
                header[key.strip().lower()] = value.strip().strip('"').strip("'")
            return header, "\n".join(lines[i + 1:]).strip()
    return {}, ""


def parse_agent_file(path: Path) -> AgentInfo:
    """Analiza un .md y decide si es un agente compliente e indexable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return AgentInfo(path, reason="read_error")

    if len(text.splitlines()) > AGENT_MAX_LINES:
        return AgentInfo(path, reason="too_long")

    header, body = parse_frontmatter(text)
    if not header:
        return AgentInfo(path, reason="no_header")

    name = header.get("name", "").strip()
    description = header.get("description", "").strip()
    skills = parse_list(header.get("skills", "")) if header.get("skills") else []
    info = AgentInfo(path, name=name, description=description, body=body, skills=skills)
    if not name or not description:
        info.reason = "missing_fields"
    elif not body:
        info.reason = "empty_body"
    else:
        info.valid = True
    return info


def load_agents(directory: Path) -> List[AgentInfo]:
    """Indexa todos los `<directory>/*.md` (validos e invalidos)."""
    if not directory.is_dir():
        return []
    return [parse_agent_file(p) for p in sorted(directory.glob("*.md"))]


def active_agent(config: Dict[str, object]) -> Optional[AgentInfo]:
    """AgentInfo del agente activo (config `agent`), o None si no hay/valido."""
    name = str(config.get("agent") or "").strip()
    if not name:
        return None
    directory = resolve_dir(str(config.get("agents_dir") or ".pbl/agents"))
    for info in load_agents(directory):
        if info.valid and info.name == name:
            return info
    return None


def active_agent_prompt(config: Dict[str, object]) -> str:
    """Cuerpo del agente activo (config `agent`), o "" si no hay/non-compliant."""
    info = active_agent(config)
    return info.body if info else ""
