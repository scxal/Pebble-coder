#!/usr/bin/env python3
"""Estado de la conversacion: historial de sesion y compactado del contexto.

Modulo hoja: no importa nada del proyecto (ni de `agent.py`) para no crear ciclos.
El cliente LLM y los textos traducibles los inyecta quien lo usa:

    summary = session.summarize(llm, config)
"""
from typing import Any, Callable, Dict, List, Optional

HISTORY_MAX_MESSAGES = 6  # ultimos 3 intercambios (pregunta + respuesta final)

_COMPACT_SYSTEM = (
    "Summarize the conversation below so that it can replace the original history.\n"
    "Keep the decisions taken, the file paths, the commands, the constraints and the "
    "open questions. Drop the small talk and the failed attempts.\n"
    "Answer with the summary only, without any preamble."
)


def update_history(history: List[Dict[str, str]], user_input: str, answer: str) -> None:
    """Guarda el intercambio terminado y recorta al limite de memoria de sesion."""
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": answer or ""})
    if len(history) > HISTORY_MAX_MESSAGES:
        del history[: len(history) - HISTORY_MAX_MESSAGES]


class Session:
    """Conversacion en curso: el historial que se envia al modelo en cada turno."""

    def __init__(self, history: Optional[List[Dict[str, str]]] = None):
        self.history: List[Dict[str, str]] = list(history) if history else []

    # --- contexto -------------------------------------------------
    def is_empty(self) -> bool:
        return not self.history

    def clear(self) -> int:
        """ vacia el contexto. Devuelve cuantos mensajes se han quitado."""
        removed = len(self.history)
        self.history = []
        return removed

    def add(self, user_input: str, answer: str) -> None:
        update_history(self.history, user_input, answer)

    def replace(self, messages: List[Dict[str, str]]) -> None:
        """Sustituye el contexto completo (usado por el compactado)."""
        self.history = list(messages)

    def transcript(self) -> str:
        """Render legible del historial para el resumidor."""
        lines: List[str] = []
        for message in self.history:
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            if message.get("role") == "assistant":
                lines.append(f"Asistente: {content}")
            else:
                lines.append(f"Usuario: {content}")
        return "\n\n".join(lines)

    # --- compactado -----------------------------------------------
    def summarize(self, llm: Callable[[List[Dict[str, str]], Dict[str, Any]], str],
                  config: Dict[str, Any]) -> str:
        """Resume el contexto con el LLM. Propaga la excepcion si la llamada falla."""
        messages = [
            {"role": "system", "content": _COMPACT_SYSTEM},
            {"role": "user", "content": self.transcript()},
        ]
        return llm(messages, config)
