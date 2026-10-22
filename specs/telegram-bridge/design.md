# Design — Telegram bridge (remote control of Pebble-Coder)

- **Feature id:** `telegram-bridge`
- **Implements:** `specs/telegram-bridge/requirements.md`
- **Prerequisite:** `specs/session-commands/` (already implemented)
- **Target:** Pebble-Coder (Python 3.10+, stdlib + `requests`; `python-telegram-bot` optional)

## 1. Overview

The bridge is a **second input surface for the same agent**. It does not add a prompt, a
skill or a tool. It translates a Telegram message into a line of CLI syntax, hands that
line to the thread that owns the REPL, captures what the REPL prints, and sends it back.

```
  Telegram                telegram_bridge.py              remote.py              agent.py / menu.py
  ────────                ───────────────────              ────────              ────────────────────
  message ──poll──►  handler ──translate──►  SessionLine ──queue──►  REPL loop ──► dispatch_line()
                              │                                    │                    │
                              │                          ApprovalBroker │◄── confirm(poll) ┘
                              │                                │       │
                              └──── send_text / send_approval ─┘       └── resolve_remote()
```

Three rules shape the whole design:

1. **One owner thread.** The session context, the agent and the tools are only ever
   touched by the REPL thread. The bridge never mutates them; it queues a line and waits.
2. **No key-semantics reuse.** The terminal's approval menu treats a bare `Enter` on the
   default row as *Yes*. A remote answer is therefore **never** delivered as a keystroke:
   it travels through an explicit boolean.
3. **Deny by default.** Every approval path that is not an explicit *yes* denies the tool.

## 2. Module layout

| Module | Responsibility | Third-party deps |
|---|---|---|
| `remote.py` *(new)* | Transport-agnostic pieces: the queue of remote lines, the approval broker, the stdout capture. | none |
| `telegram_bridge.py` *(new)* | Everything Telegram: credentials, the bot, the handlers, the message translation. | `python-telegram-bot` (imported lazily) |
| `menu.py` | Grows a `poll` seam so the terminal can be interrupted by an external decision or an external line. | none |
| `agent.py` | Grows the command contract (`args`), the approval path (`request_approval`), the loop (`dispatch_line`) and the new `/rc` command. | none |
| `session.py` | Grows two optional attributes: `remote` and `approvals`. | none |

```
agent.py  ──imports──►  remote.py            (leaf, no project imports)
agent.py  ──imports──►  telegram_bridge.py  (imports remote.py; imports PTB lazily)
telegram_bridge.py  ──imports──►  remote.py
```

`remote.py` never imports `telegram_bridge.py`; the dependency points the other way, so
the Telegram-specific code can be replaced by a fake in the tests.

## 3. `remote.py`

### 3.1 The transport interface

```python
class RemoteTransport:
    """Lo que el puente necesita para hablar con un chat."""

    def send_text(self, target: int, text: str) -> None: ...
    def send_approval(self, target: int, action: str, preview: str,
                       request_id: int) -> None: ...
    def resolve_approval(self, request_id: int, approved: bool) -> None: ...
```

`TelegramBridge` implements it for real; the tests implement it with an in-memory list.

### 3.2 The controller: the queue of remote lines

```python
class SessionLine:
    """Una linea remota pendiente: su texto y el chat de destino."""
    def __init__(self, text: str, target: int):
        self.text = text
        self.target = target


class RemoteController:
    """Cola de lineas remotas pendientes y transporte asociado."""

    def __init__(self):
        self._queue: queue.Queue[SessionLine] = queue.Queue()
        self._transport: Optional[RemoteTransport] = None
        self._current: Optional[SessionLine] = None

    # -- transporte ------------------------------------------------
    def set_transport(self, transport: RemoteTransport) -> None
    def clear_transport(self) -> None
    @property
    def enabled(self) -> bool:
        return self._transport is not None

    # -- cola ------------------------------------------------------
    def push(self, text: str, target: int) -> None
    def poll_text(self) -> Optional[str]:
        """Saca la siguiente linea y la recuerda. None si no hay ninguna."""
        line = self._queue.get_nowait() if not self._queue.empty() else None
        if line is None:
            return None
        self._current = line
        return line.text

    def current_target(self) -> Optional[int]:
        """El chat de la linea que se acaba de sacar (None si era local)."""
        return self._current.target if self._current else None

    def current_line(self) -> Optional[SessionLine]
    def send(self, target: int, text: str) -> None
```

`poll_text()` is the callback handed to `menu.command_input(poll=...)`. It returns the
**text** (the menu only knows how to return a string) and remembers the line so the REPL
can ask for the target afterwards.

`queue.Queue` is used instead of a `list` because the bridge thread is the producer and
the REPL thread is the consumer; `Queue` gives the happens-before guarantee for free.

### 3.3 The approval broker

```python
class _PendingApproval:
    def __init__(self, request_id: int, action: str, preview: str, deadline: float):
        self.request_id = request_id
        self.action = action
        self.preview = preview
        self.deadline = deadline
        self.approved = False
        self.remote_decision: Optional[bool] = None


class ApprovalBroker:
    """Aprobaciones de herramientas: responden el terminal o el control remoto."""

    def __init__(self, timeout: float = 120.0):
        self._lock = threading.Lock()
        self._pending: Optional[_PendingApproval] = None
        self._next_id = 0
        self._timeout = timeout
        self._transport: Optional[RemoteTransport] = None

    def set_transport(self, transport) -> None
    def enabled(self) -> bool          # True si hay transporte (bot activo)

    def begin(self, action: str, preview: str) -> int:
        """Registra la peticion, avisa al transporte y devuelve su id."""

    def poll(self) -> Optional[bool]:
        """Decision remota pendiente; None si todavia no hay ninguna.

        Devuelve False (denegar) si se paso el plazo de espera.
        """

    def settle(self, approved: bool) -> bool:
        """Cierra la peticion con la decision final y la notifica al transporte."""

    def end(self) -> None:
        """Descarta la peticion (la resolvio el terminal)."""

    def resolve_remote(self, request_id: int, approved: bool) -> bool:
        """Resuelve desde el control remoto. False si el id no es el pendiente."""
```

Semantics:

- `begin()` creates the pending request, publishes it to the transport (the bot sends the
  message with the yes/no control) and returns an id used as the Telegram callback data.
- `poll()` is called by the terminal menu on every iteration. It returns the remote
  decision when there is one. If the deadline has passed it returns `False` — the
  fail-safe: **an unanswered request denies the tool**.
- `settle()` records the final decision, tells the transport (so the chat can update the
  message) and returns it.
- `resolve_remote()` is called from the bot thread. It only accepts the id of the
  *current* pending request, so a stale button press does nothing.

The first answer wins by construction: the menu returns the remote decision only if
`poll()` produced it before the terminal was touched; otherwise the terminal's own choice
is the one that gets settled, and a later remote answer finds no pending request.

### 3.4 Capturing the output for the reply

```python
@contextlib.contextmanager
def capture_stdout():
    """Captura stdout (escribiendo tambien en el original) para enviarlo al chat."""
```

The context manager replaces `sys.stdout` with a tee that writes to the original stream
**and** to a `StringIO`. The terminal user sees the turn exactly as usual (FR-4.4) and
the bridge gets the text to send back (FR-7.2).

```python
def strip_ansi(text: str) -> str:
    """Quita las secuencias de control del terminal."""
```

The captured text is stripped of ANSI sequences and of the lines that become empty after
the strip (the statistics bar writes cursor movements that would otherwise show up as
garbage in the chat).

## 4. `menu.py` — the `poll` seam

Three functions grow an optional `poll` callback. When it is `None` the behaviour is
**exactly** what it is today (blocking read, same cadence).

### 4.1 `_read_key` with a timeout

```python
def _read_key(fd: int, quit_chars: tuple = ("q", "Q"),
              timeout: Optional[float] = None) -> Optional[str]:
```

With a `timeout`, the function waits at most that long for the first byte and returns
`None` when nothing arrives. Without it, the behaviour is unchanged (blocking read).

### 4.2 `run_menu(..., poll=None)`

The menu loop asks `_read_key` for a key with a short timeout (`_POLL_INTERVAL = 0.2`)
when a `poll` is present. On a `None` key the `poll` is consulted:

```python
            key = _read_key(fd, timeout=_POLL_INTERVAL if poll is not None else None)
            if key is None:
                value = poll()
                if value is not None:
                    return value      # el menu se cierra con la decision externa
                continue
```

`run_menu` now returns `Optional[Any]`: the value produced by the poll, or `None` when
the user closed the menu normally. Existing callers ignore the return value.

### 4.3 `confirm(..., poll=None)`

```python
def confirm(title, yes_label=None, no_label=None, poll=None) -> bool:
    result = {"allowed": False}
    items = [...]
    decision = run_menu(title, items, hint=t("menu_hint_confirm"), poll=poll)
    if decision is not None:
        return bool(decision)      # decision externa (remota)
    return result["allowed"]       # decision del terminal
```

The terminal semantics are untouched: `Enter` on the highlighted row is still *Yes*,
`Esc`/`q`/Ctrl+C are still *No*.

### 4.4 `command_input(..., poll=None)`

```python
def command_input(prompt, commands, descriptions=None, on_tick=None, poll=None) -> str:
```

The wait loop becomes:

```python
        last_tick = time.monotonic()
        while True:
            timeout = _POLL_INTERVAL if poll is not None else (
                _STATUS_TICK if on_tick is not None else None)
            if timeout is not None:
                ready, _, _ = select.select([fd], [], [], timeout)
                if not ready:
                    now = time.monotonic()
                    if on_tick is not None and now - last_tick >= _STATUS_TICK:
                        last_tick = now
                        on_tick()
                    if poll is not None and not buffer:
                        text = poll()
                        if text is not None:
                            return text
                    continue
            key = _read_key(fd, quit_chars=())
```

Two details:

- The statistics bar keeps its 4-second cadence: with a `poll` present the select
  timeout drops to 0.2 s, but `on_tick` is only called when `_STATUS_TICK` has elapsed.
- **The local buffer is never discarded.** The remote line is only taken when the user
  has not typed anything; if the user is mid-sentence the remote line waits in the queue
  until the next turn. This keeps the "no races on the keyboard" promise of the terminal
  intact.

## 5. `agent.py`

### 5.1 The command contract grows an `args` parameter

`handle_command` currently throws away everything after the command word
(`agent.py:1033`: `cmd = user_input.strip().split()[0].lower()`), which makes
`/agent frontend-developer` indistinguishable from `/agent`.

```python
def handle_command(user_input, config, tools_config, session=None, args="") -> ...
def cmd_xxx(config, tools_config, session=None, args="") -> ...
```

`handle_command` computes `args` as the remainder of the line and forwards it. The
parameter is optional, so every existing call site keeps working.

### 5.2 Non-interactive `/agent` and `/skills`

The terminal versions are interactive menus; the remote versions need to be one-shot.
The same handler serves both, distinguished by the presence of `args`:

```python
def cmd_agent(config, tools_config, session=None, args=""):
    infos = agents.load_agents(agents.resolve_dir(str(config.get("agents_dir") or ".pbl/agents")))
    if args:
        return _set_agent_from_args(config, infos, args)
    ... menu interactivo actual ...
```

| Line | Effect |
|---|---|
| `/agent` | interactive menu (unchanged) |
| `/agent list` | prints the available agents and the active one |
| `/agent <name>` | activates that agent and persists it to `config.json` |
| `/agent none` | deactivates the agent |
| `/skills` | interactive menu (unchanged) |
| `/skills list` | prints the visible skills and the active ones |
| `/skills <a,b>` | activates exactly those skills and persists them |
| `/skills none` | deactivates every skill |

An unknown name prints an error and changes nothing (FR-5.5). The persistence uses the
same `save_config` as the menus, so a change made from the phone is visible in the
terminal and survives a restart.

### 5.3 The approval path

```python
def request_approval(action: str, preview: str, broker=None) -> bool:
    """Pide permiso para ejecutar la herramienta. Sin broker, solo el terminal."""
    if broker is None or not broker.enabled():
        return confirm(t("tool_confirm_question"))
    request_id = broker.begin(action, preview)
    try:
        decision = confirm(t("tool_confirm_question"), poll=broker.poll)
        return broker.settle(decision)
    finally:
        broker.end()
```

The approval block in `run_react_agent` replaces its direct `confirm(...)` call with
`request_approval(action, preview, broker)`. Everything else (the header, the preview,
the denial observation) stays as it is, so the terminal experience does not change when
the bridge is off.

`broker.begin()` publishes the request to the transport, which sends the Telegram message
with the yes/no control; `broker.settle()` tells the transport how it ended, so the chat
can update the message (FR-6.5, FR-6.6).

### 5.4 The REPL loop

The body of the loop is extracted into a closure so the local and the remote paths share
it:

```python
    def dispatch_line(user_input: str) -> None:
        if user_input.startswith("/"):
            tools_config, prompt = handle_command(user_input, config, tools_config, session)
            statistics.idle_tick()
            if prompt:
                run_turn(prompt)
        else:
            run_turn(user_input)
```

and the loop becomes:

```python
    while True:
        commands = load_commands() + skill_commands(config)
        ...
        try:
            user_input = command_input(prompt_label, command_names, command_descs,
                                       on_tick=statistics.idle_tick,
                                       poll=remote.poll_text).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue

        target = remote.current_target()
        if target is not None:
            # Linea remota: se ejecuta aqui (un solo hilo) y se responde al chat.
            with capture_stdout() as captured:
                dispatch_line(user_input)
            remote.send(target, strip_ansi(captured.getvalue()))
            continue

        if user_input.lower() in EXIT_COMMANDS:
            break

        dispatch_line(user_input)
```

Two properties fall out of this shape:

- **A remote line can never end the session**: the exit check only applies to local
  lines. `/exit` from Telegram is refused by the bridge before it ever reaches the queue.
- **The remote turn is executed by the REPL thread**, so the session context is mutated
  in exactly one place (FR-4.6).

### 5.5 The `/rc` command

```python
def cmd_rc(config, tools_config, session=None, args=""):
    """Activa o desactiva el control remoto por Telegram."""
    controller = getattr(session, "remote", None)
    if controller is None:
        print(red(t("rc_unavailable")))
        return tools_config, None
    if controller.enabled:
        controller.clear_transport()
        print(yellow(t("rc_stopped")))
        return tools_config, None
    try:
        from telegram_bridge import start_bridge
    except ImportError as exc:
        print(red(t("rc_missing_dependency").format(exc=exc)))
        return tools_config, None
    ok, error = start_bridge(controller, session.approvals)
    if not ok:
        print(red(error))
        return tools_config, None
    print(green(t("rc_started").format(user=...)))
    return tools_config, None
```

`start_bridge` reads the environment, builds the bridge and starts the thread; it returns
`(False, message)` instead of raising, so `/rc` can never break the REPL (FR-1.4).

`/rc` is registered in `COMMANDS`, in `defaults/commands.json` and in the fallback list
of `load_commands()`. It is **not** reachable from Telegram (it is in the refused list).

### 5.6 `session.py`

The `Session` object grows two optional attributes, set by `main()`:

```python
class Session:
    def __init__(self, history=None):
        self.history = ...
        # Superficie remota: la inyecta `main()` (ver `remote.py`).
        self.remote = None       # RemoteController
        self.approvals = None    # ApprovalBroker
```

`session.py` stays free of third-party imports: the attributes are duck-typed and
default to `None`, so `Session` can be used without the remote feature at all.

## 6. `telegram_bridge.py`

### 6.1 Credentials

```python
API_KEY_ENV = "PBL_TELEGRAM_API_KEY"
USER_ENV = "PBL_TELEGRAM_USER"


def read_credentials(env=None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Devuelve (token, usuario, error). El error es None si todo esta bien."""
```

- The environment is read **when `/rc` runs** (FR-2.3).
- A missing or empty variable produces a message naming **both** variables (FR-2.4).
- The token is never logged and never written to disk (FR-2.5).

### 6.2 Authorization

```python
def is_authorized(user_id, expected) -> bool:
    """True si el emisor es el usuario autorizado."""
```

- `expected` is a numeric id: the comparison is `int(user_id) == int(expected)`, so `123`
  never matches `1234` (FR-3.6).
- `expected` is not a number: it is treated as a username and compared with the sender's
  `@username`, case-insensitively (FR-3.2).
- An empty `expected` authorizes nobody.

A rejected message triggers the red warning:

```python
    def _warn_unauthorized(self, update) -> None:
        _ORIGINAL_STDOUT.write(red(t("rc_unauthorized").format(user=...)) + "\n")
```

`_ORIGINAL_STDOUT` is captured at import time, so the warning does not end up inside a
captured reply and does not inherit the tee installed during a remote turn. The message
never contains the token (FR-3.5).

### 6.3 Translating a Telegram message into a CLI line

```python
def translate_message(text: str) -> Tuple[str, str]:
    """Devuelve (kind, payload).

    kind == "line"   -> payload es la linea de CLI que hay que ejecutar
    kind == "refuse" -> payload es el motivo de la negativa
    kind == "ignore" -> la mensaje no se sirve
    """
```

| Telegram | Result |
|---|---|
| `hola` | `("line", "hola")` — un turno normal |
| `/agent` | `("line", "/agent list")` |
| `/agent foo` | `("line", "/agent foo")` |
| `/skills` | `("line", "/skills list")` |
| `/skills a,b` | `("line", "/skills a,b")` |
| `/new` | `("line", "/new")` |
| `/compact` | `("line", "/compact")` |
| `/help` | `("line", "/help")` — el puente responde con la lista de comandos |
| `/settings`, `/tools` | `("refuse", ...)` — solo en la terminal |
| `/exit`, `/quit` | `("refuse", ...)` — no se puede cerrar la sesion desde fuera |
| anything else starting with `/` | `("ignore", ...)` |

The `@botname` suffix (`/agent@mi_bot foo`) is stripped, so the bot also works in a
group.

`/help` is handled by the bridge itself: the CLI has no `/help` command, so the bridge
replies with the list of the available remote commands and states that the session is
the terminal one (FR-5.8).

### 6.4 The bot

```python
class TelegramBridge:
    """Implementa `remote.RemoteTransport` sobre python-telegram-bot."""

    def __init__(self, token, user, controller, broker, on_unauthorized=None):
        ...

    def start(self) -> None:      # arranca el hilo
    def stop(self) -> None:       # para el hilo y cierra el bot
    # RemoteTransport
    def send_text(self, target, text) -> None
    def send_approval(self, target, action, preview, request_id) -> None
    def resolve_approval(self, request_id, approved) -> None
```

The thread:

```python
    def _run(self) -> None:
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        self._loop = loop
        self._ready.set()
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self._error = exc
        finally:
            self._loop = None

    async def _serve(self) -> None:
        from telegram.ext import Application
        app = Application.builder().token(self._token).build()
        self._app = app
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        app.add_handler(CommandHandler("help", self._on_help))
        app.add_handler(CallbackQueryHandler(self._on_callback))
        self._stop_event = asyncio.Event()
        await app.initialize()
        await app.updater.start_polling()
        try:
            await self._stop_event.wait()
        finally:
            await app.updater.stop()
            await app.shutdown()
```

Why not `run_polling()`: it owns the loop and never returns, so the bridge could not be
stopped deterministically. Driving `initialize()` / `start_polling()` / `shutdown()` by
hand gives `/rc` a clean off switch and lets the bot report a startup failure.

`python-telegram-bot` is asyncio-only and not thread-safe, so the **whole**
`Application` lives in that one thread with one loop. Everything the main thread needs
to do from the bot side goes through `asyncio.run_coroutine_threadsafe`:

```python
    def _call(self, coro) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=10)
        except Exception:
            pass
```

### 6.5 The handlers

```python
    async def _on_text(self, update, context) -> None:
        if not is_authorized(update.effective_user.id, self._user):
            self._warn_unauthorized(update)
            return
        kind, payload = translate_message(update.message.text)
        if kind == "refuse":
            await update.message.reply_text(payload)
            return
        if kind == "ignore":
            return
        self._controller.push(payload, update.effective_chat.id)
```

```python
    async def _on_callback(self, update, context) -> None:
        query = update.callback_query
        request_id, approved = _parse_callback(query.data)
        if request_id is None:
            await query.answer()
            return
        self._broker.resolve_remote(request_id, approved)
        await query.answer()
```

The approval message carries an inline keyboard:

```python
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t("rc_yes"), callback_data=f"pbl:yes:{request_id}"),
             InlineKeyboardButton(t("rc_no"), callback_data=f"pbl:no:{request_id}")],
        ])
        await context.bot.send_message(chat_id, text, reply_markup=keyboard)
```

The callback data carries the request id, so a press on a stale button is rejected by
`resolve_remote()` (which only accepts the current pending id).

## 7. Threading model

| Thread | Owns | Talks to the other threads through |
|---|---|---|
| Main (REPL) | the session, the agent, the tools, the terminal | `RemoteController` queue, `ApprovalBroker` lock |
| Bridge (asyncio) | the Telegram `Application`, the bot loop | the same queue and lock |

Rules:

- Only the main thread touches `sys.stdout` (except the unauthorized warning, which is
  written to the original stream on purpose).
- Only the main thread reads `stdin`.
- The bot never calls the agent directly: it queues a line.
- `queue.Queue` and `threading.Lock` provide the memory barriers; no other
  synchronisation primitive is needed.

## 8. Error handling

| Situation | Behaviour |
|---|---|
| `python-telegram-bot` not installed | `/rc` prints a red message; the app keeps working (FR-8.2). |
| `PBL_TELEGRAM_API_KEY` / `PBL_TELEGRAM_USER` missing | `/rc` prints a red message naming both variables; the bridge does not start (FR-2.4). |
| The token is rejected by Telegram | The thread stores the error; `/rc` reports it; the app keeps working (FR-8.3). |
| The network drops while polling | `python-telegram-bot` retries internally; if the bot dies, the error is stored and reported on the next `/rc`. |
| A message arrives from an unauthorized user | Ignored + red warning on the terminal (FR-3.3, FR-3.4). |
| The chat asks for `/settings` | Refused with an explanation (FR-5.2). |
| A turn fails | The error text is part of the captured output and is sent in the reply (FR-7.4). |
| An approval is never answered | Denied when the deadline passes (FR-6.4). |

## 9. Testing strategy

Everything below runs **without a network and without the Telegram library**: the
Telegram-specific code is behind the `RemoteTransport` interface, and the tests use a
fake.

| Test | Level | What it pins |
|---|---|---|
| `read_credentials` with both / one / none | unit | FR-2.4 |
| `is_authorized` with matching, mismatching, numeric-prefix and username cases | unit | FR-3.1, FR-3.2, FR-3.6 |
| The unauthorized warning is red and has no token | unit | FR-3.4, FR-3.5 |
| `translate_message` for every command form | unit | FR-5.1, FR-5.2, FR-5.8 |
| `RemoteController.push` / `poll_text` / `current_target` | unit | the queue contract |
| `capture_stdout` captures and still writes to the terminal | unit | FR-4.4, FR-7.2 |
| `strip_ansi` removes the control characters | unit | FR-7.2 |
| `ApprovalBroker.begin/poll/settle/end` | unit | FR-6.1 |
| `resolve_remote` with a stale id does nothing | unit | FR-6.5 |
| An approval that nobody answers denies the tool | unit | FR-6.4 |
| `confirm(poll=...)` returns the external decision | unit | FR-6.2 |
| `confirm(poll=...)` keeps the terminal semantics without a poll | unit | FR-4.x, NFR-5 |
| `command_input(poll=...)` returns the remote text | unit (pty) | the injection seam |
| `command_input` does not take a remote line while the user is typing | unit (pty) | the buffer rule |
| A remote line runs a normal turn and the reply is captured | integration (fake transport + fake LLM) | FR-4.1, FR-4.3, FR-7.1 |
| `/agent <name>` and `/skills a,b` from a remote line persist | integration | FR-5.3, FR-5.4, FR-5.6 |
| `/new` and `/compact` from a remote line | integration | FR-5.7 |
| An approval answered from the chat allows the tool | integration (fake transport + fake LLM) | FR-6.1, FR-6.2 |
| An approval answered "no" from the chat denies the tool | integration | FR-6.3 |
| The terminal answers an approval the chat also received | integration | FR-6.2, FR-6.6 |
| A remote line cannot end the session | integration | FR-8.1 |

Manual acceptance (needs a real bot): `/rc` connects, a message from the phone produces
a turn in the terminal, the approval buttons work, and a message from a foreign account
produces the red warning.

## 10. Alternatives considered

| Alternative | Why not |
|---|---|
| A separate daemon process talking to the CLI over a socket | A second process needs its own copy of the session, the config and the tools, and the protocol to keep them in sync is far bigger than the problem. |
| Webhooks instead of long polling | A public endpoint is needed; long polling needs no infrastructure and is a natural fit for a local tool. |
| `aiogram` instead of `python-telegram-bot` | Both are standard; `python-telegram-bot` has the wider adoption and the simpler `Application`/handler model for this use case. |
| Hand-rolled Bot API client over `requests` | No new dependency, but it means writing the protocol, the update loop and the callback plumbing by hand — exactly what the user asked not to do. |
| Reusing the terminal's keystrokes for the remote answer | `menu.confirm` treats a bare `Enter` on the default row as *Yes*: a remote "no" would approve the tool. The remote path uses an explicit boolean instead. |
| Echoing the terminal output by parsing the ANSI stream | Fragile. The tee captures the text as it is written. |
| Letting the bot call the agent directly | Two threads mutating the session. The queue keeps a single owner. |
| Adding the Telegram token to `config.json` | The token would be written to disk and copied around. The environment keeps it out of the repository and out of `~/.pbl`. |
