# Design — Session commands (`/new`, `/compact`) and automatic compaction

- **Feature id:** `session-commands`
- **Implements:** `specs/session-commands/requirements.md`
- **Target:** Pebble-Coder (Python 3.10+, stdlib + `requests`)

## 1. Overview

The conversation history becomes an explicit object owned by a new leaf module,
`session.py`. The REPL creates one `Session` per process and hands it to the command
handlers. `/new` and `/compact` are ordinary commands operating on that object, and the
automatic compaction reuses the very same code path.

```
main()                         session.py (leaf, no project imports)
  │
  ├─ session = Session()
  │
  ├─ run_turn(prompt)  ──►  session.add(prompt, answer)      # history grows
  │        │
  │        └─ after the turn: if should_autocompact(config, statistics.last_ctx()):
  │                            apply_compaction(session, config)
  │
  └─ handle_command(line, config, tools_config, session)
             ├─ /new      ─► session.clear()
             └─ /compact  ─► apply_compaction(session, config)
```

### Dependency direction

`session.py` must not import `agent.py` (the CLI needs the i18n helper `t()` and the LLM
client `call_llm()`, both of which live in `agent.py`, and `agent.py` needs `session.py`).
The cycle is broken by **injecting the collaborator**:

- `Session.summarize(llm, config)` receives the LLM callable as an argument.
- The *user-visible* strings stay in `agent.py`; `session.py` returns data, `agent.py`
  formats it.

```
agent.py  ──imports──►  session.py          (one direction only)
```

## 2. `session.py`

New module, no third-party imports, no project imports.

```python
HISTORY_MAX_MESSAGES = 6      # 3 intercambios (pregunta + respuesta final)


def update_history(history, user_input, answer) -> None:
    """Guarda el intercambio terminado y recorta al limite de memoria de sesion."""
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": answer or ""})
    if len(history) > HISTORY_MAX_MESSAGES:
        del history[: len(history) - HISTORY_MAX_MESSAGES]


class Session:
    def __init__(self, history=None):
        self.history: List[Dict[str, str]] = list(history) if history else []

    # --- contexto -------------------------------------------------
    def is_empty(self) -> bool
    def clear(self) -> int                  # devuelve cuantos mensajes se quitaron
    def add(self, user_input, answer) -> None
    def transcript(self) -> str             # render legible para el resumidor
    def replace(self, messages) -> None     # sustituye el contexto entero
    def summarize(self, llm, config) -> str # llama al LLM; propaga la excepcion
```

**Why `replace()` and not a `summary` attribute?** The context is a plain list of
`{"role", "content"}` dicts and the request builder copies it verbatim
(`agent.py:482-485`). Replacing the list keeps the contract with the model untouched: the
compacted context is just another pair of messages.

**`transcript()`** renders the history as `Usuario: …` / `Asistente: …` blocks, skipping
empty messages, so the summarizer sees the conversation, not the raw JSON.

**`summarize(llm, config)`** sends two messages:

```python
messages = [
    {"role": "system", "content": _COMPACT_SYSTEM},
    {"role": "user",   "content": self.transcript()},
]
return llm(messages, config)
```

`_COMPACT_SYSTEM` is a module constant (not translated — it is an instruction to the model,
not UI text):

> Summarize the conversation so it can replace the original history. Keep the decisions
> taken, file paths, commands, constraints and open questions. Answer with the summary
> only, no preamble.

The LLM callable is `agent.call_llm`, adapted to the new `track_stats` flag so the
summarization does not overwrite the status-bar counters (requirement FR-2.4).

## 3. `agent.py`

### 3.1 Imports and re-exports

```python
from session import Session, update_history
from session import HISTORY_MAX_MESSAGES as _HISTORY_MAX_MESSAGES
```

`agent.update_history` and `agent._HISTORY_MAX_MESSAGES` keep working (the existing test
`tests/test_history.py` imports them from `agent`), but the implementation now lives in
`session.py`.

### 3.2 `call_llm` gains a statistics switch

```python
def call_llm(messages, config, track_stats: bool = True) -> str:
    ...
    if track_stats:
        statistics.note_usage(data.get("usage"))
```

`stream_llm` is untouched. The flag exists only so the compaction call is invisible in the
status bar.

### 3.3 Command handler contract

Every handler becomes:

```python
def cmd_xxx(config, tools_config, session=None) -> Tuple[Dict[str, Any], Optional[str]]:
```

`session` is **optional** so existing direct call sites
(`tests/test_skills.py:201` calls `agent.handle_command("/alpha", cfg, {"t": {}})`) keep
working. `handle_command` gains the same optional parameter and forwards it:

```python
def handle_command(user_input, config, tools_config, session=None):
    ...
    return handler(config, tools_config, session)
```

Handlers that do not need the session simply ignore it. `/new` and `/compact` degrade
gracefully when `session is None` (they report that the operation is unavailable — this
cannot happen from the REPL, where the session always exists).

### 3.4 `/new`

```python
def cmd_new(config, tools_config, session=None):
    if session is None:
        print(red(t("session_unavailable")))
        return tools_config, None
    removed = session.clear()
    print(green(t("new_session_cleared").format(count=removed)))
    return tools_config, None
```

No LLM call, nothing appended to the history.

### 3.5 `/compact` and the shared compaction routine

```python
def apply_compaction(session, config) -> bool:
    """Resume el contexto en un par de mensajes. Devuelve True si se compacto."""
    if session is None or session.is_empty():
        return False
    try:
        summary = session.summarize(lambda m, c: call_llm(m, c, track_stats=False), config)
    except Exception as exc:
        print(red(t("compact_error").format(exc=exc)))
        return False
    summary = (summary or "").strip()
    if not summary:
        print(red(t("compact_error").format(exc=t("compact_empty_summary"))))
        return False
    session.replace([
        {"role": "user", "content": t("compact_summary_prefix") + summary},
        {"role": "assistant", "content": t("compact_summary_ack")},
    ])
    return True


def cmd_compact(config, tools_config, session=None):
    if session is None or session.is_empty():
        print(yellow(t("compact_empty")))
        return tools_config, None
    if apply_compaction(session, config):
        print(green(t("compact_done")))
    return tools_config, None
```

The compaction turn is **not** a turn: `cmd_compact` returns `None` as the prompt, so
`run_turn` is never invoked and `update_history` is never called for it (FR-2.3).

Failure handling: the exception is caught **before** `session.replace()`, so a failed
compaction leaves the context untouched (FR-2.6).

### 3.6 Automatic compaction

```python
def autocompact_threshold(config) -> int:
    try:
        value = int(config.get("autocompact_threshold", 85))
    except (TypeError, ValueError):
        return 85
    return max(1, min(100, value))


def should_autocompact(config, ctx_tokens) -> bool:
    if not is_enabled(config, "autocompact", True):
        return False
    if not ctx_tokens or ctx_tokens <= 0:
        return False
    try:
        window = int(config.get("context_window", 32768))
    except (TypeError, ValueError):
        return False
    if window <= 0:
        return False
    return (float(ctx_tokens) / window) * 100.0 >= autocompact_threshold(config)
```

The check runs in the session turn wrapper, **after** the turn is recorded:

```python
def run_turn(prompt: str) -> None:
    statistics.begin_answer()
    answer = run_react_agent(prompt, config, tools_config, session.history)
    statistics.end_answer()
    session.add(prompt, answer)
    if should_autocompact(config, statistics.last_ctx() or 0):
        if apply_compaction(session, config):
            print(green(t("autocompact_triggered")))
```

`statistics.last_ctx()` returns the exact `prompt_tokens` when the server reported usage
and the `chars/4` estimate otherwise (`statistics.py:170-214`). `note_context()` is called
on every ReAct iteration with the outgoing messages, so the value is always fresh after a
turn.

FR-3.8 (no loop): the check happens once per turn, and a compaction shrinks the context, so
the next turn starts far below the threshold.

### 3.7 Settings rows

Appended **after** the `theme` row, so the digit shortcuts 1-9 keep pointing at the same
rows (FR-5.2):

```python
MenuItem(t("label_autocompact"), "toggle",
         value=config.get("autocompact", "on"), on_change=setter("autocompact")),
MenuItem(t("label_autocompact_threshold"), "text",
         value=config.get("autocompact_threshold", 85),
         validate=_validate_percentage, on_change=setter("autocompact_threshold")),
```

New validator next to `_validate_positive_int`:

```python
def _validate_percentage(raw: str) -> int:
    value = int(raw)
    if not (1 <= value <= 100):
        raise ValueError(raw)
    return value
```

The switch is stored as the string `"on"`/`"off"`, the convention used by every other
config toggle, and read back through `is_enabled()`.

### 3.8 Command registration

Three places, as the project already documents:

1. `COMMANDS` dict — `"/new": cmd_new`, `"/compact": cmd_compact` (appended after
   `/skills`, so the "unknown command" message becomes
   `"/settings, /tools, /editor, /agent, /skills, /new, /compact, /exit, /quit"`).
2. `defaults/commands.json` — same two entries, same relative order.
3. The hardcoded fallback list inside `load_commands()`.

`menu._POPUP_MAX` is raised from 8 to 10: the static command list reaches 8 with this
feature and 9 with `/rc` in the `telegram-bridge` feature, and the popup must keep the
exit command reachable (FR-6.4).

## 4. `pbl_home.py` — upgrade of existing installations

`bootstrap()` only copies a file when it is **missing**, so an installation created before
this feature never receives the new config keys or the new translation strings: the
settings rows would show empty labels and the commands would be missing from the popup.

New function:

```python
def sync_defaults() -> None:
    """Añade a los ficheros de ~/.pbl las claves nuevas de defaults/ sin tocar los valores."""
```

Rules:

| File | Merge |
|---|---|
| `config.json` | Top-level keys. A key present in `defaults/` and absent in the home file is added with the default value. Existing keys are never modified. New keys are appended at the end. |
| `commands.json` | The `"commands"` object: missing command entries are added, existing ones are kept. |
| `translations_es.json`, `translations_en.json` | Section by section (`ui`, `menu`, `tools`, `parser`): missing keys are added, existing ones are kept. |

The file is rewritten **only** when something was actually added, with the same format the
rest of the application uses (`indent=2`, `ensure_ascii=False`, trailing newline).

`sync_defaults()` is called from `bootstrap()` right after the copy step, so it runs on
every start and is a no-op once the installation is up to date.

## 5. Data files

`defaults/config.json` gains:

```json
  "autocompact": "on",
  "autocompact_threshold": 85,
```

`defaults/commands.json` gains `"/new": "cmd_new"` and `"/compact": "cmd_compact"`.

`defaults/translations_es.json` and `defaults/translations_en.json` gain the `ui` keys:

| Key | es | en |
|---|---|---|
| `cmd_new` | Nueva sesión | New session |
| `cmd_compact` | Compactar contexto | Compact context |
| `label_autocompact` | Compactado automático | Automatic compaction |
| `label_autocompact_threshold` | Umbral de compactado (%) | Compaction threshold (%) |
| `new_session_cleared` | Contexto limpo ({count} mensajes) | Context cleared ({count} messages) |
| `compact_done` | Contexto compactado | Context compacted |
| `compact_empty` | No hay nada que compactar | Nothing to compact |
| `compact_error` | No se pudo compactar: {exc} | Could not compact: {exc} |
| `compact_summary_prefix` | Resumen de la conversación anterior: | Summary of the previous conversation: |
| `compact_summary_ack` | Contexto resumido; continúo desde aquí. | Context summarized; continuing from here. |
| `autocompact_triggered` | Compactado automático por umbral de contexto | Automatic compaction triggered by context threshold |
| `session_unavailable` | Sesión no disponible | Session unavailable |

## 6. Testing strategy

| Test | Level | What it pins |
|---|---|---|
| `Session.clear()` empties the context | unit | FR-1.1 |
| `Session.add()` trims to `HISTORY_MAX_MESSAGES` | unit | unchanged behaviour |
| `Session.summarize()` sends a system+user pair and returns the text | unit (fake LLM) | FR-2.2 |
| `/compact` replaces the context with the summary pair | unit (fake LLM) | FR-2.1, AC-3 |
| The compaction request never reaches the history | unit | FR-2.3, AC-4 |
| A failing LLM leaves the context untouched | unit | FR-2.6, AC-5 |
| `/compact` on an empty context makes no call | unit | FR-2.5, AC-6 |
| `should_autocompact()` is true at and above the threshold, false below | unit | FR-3.2, AC-7/8 |
| `/new` does not change agent/skills | unit | FR-1.3, AC-2 |
| `pbl_home.sync_defaults()` adds missing keys and keeps user values | unit | FR-7, AC-12 |
| The two new settings rows persist | unit | FR-5.3, AC-9/10 |
| The popup shows `/new` and `/compact`; the exit command is still reachable | E2E (pty) | FR-6.2, AC-11 |
| The unknown-command message lists the new commands | E2E (pty) | FR-6.3, AC-11 |

Existing tests to update:

- `tests/test_commands.py:107` — the expected unknown-command string.
- `tests/test_commands.py:61-77` — the popup navigation now needs two extra `↓` presses to
  reach `/exit`.
- `tests/test_settings_menu.py:105` — the same unknown-command string.

## 7. Alternatives considered

| Alternative | Why not |
|---|---|
| Keep the history as a module-level global in `agent.py` | Global state leaks between tests and between the CLI and the future remote surface. |
| Let `/compact` return the summary as the "next prompt" | The handler contract would run the summary as a *turn*, polluting the context it is meant to replace. |
| Tokenize with `tiktoken` | New dependency, and the models in use are local ones whose tokenizer is unknown. The server's own `prompt_tokens` is exact and already available. |
| Store the context in a file | The context is a conversation, not configuration; persistence is explicitly out of scope. |
| Rebuild the whole context from scratch on `/new` | Same effect as clearing, but loses the object identity that the remote surface will hold. |
