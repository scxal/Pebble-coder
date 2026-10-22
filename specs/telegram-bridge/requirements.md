# Requirements — Telegram bridge (remote control of Pebble-Coder)

- **Feature id:** `telegram-bridge`
- **Status:** approved (2026-10-22)
- **Phase:** 2 of 2 (builds on `session-commands`, which must exist first)
- **Prerequisite:** `specs/session-commands/` — `/new`, `/compact` and the `Session` object
  already exist and are reused as-is.

## 1. Context

Pebble-Coder is a terminal ReAct agent. The session lives in one process: one system
prompt, one tool set, one history. A user who is away from the machine has no way to keep
working with the same session.

This feature adds a **Telegram bridge**: a second surface that drives the *same* running
agent. The bridge is not a second agent, not a second prompt and not a set of extra
skills — it is another way to type into the same REPL, plus a way to answer the tool
approval prompt from a phone.

The bridge is started on demand with `/rc` (remote control) and lives only for the
duration of the session.

## 2. Scope

In scope:

- A `/rc` command that starts (and stops) the Telegram bridge for the current session.
- Credentials read from the environment: `PBL_TELEGRAM_API_KEY` (bot token) and
  `PBL_TELEGRAM_USER` (the authorized user id).
- Authorization: only the authorized user is served; any other sender is rejected and
  raises a red warning on the terminal.
- A minimal command set from Telegram: `/agent`, `/skills`, `/new`, `/compact`, `/help`.
- Free text from Telegram is an ordinary turn of the same agent.
- Tool approvals answerable from Telegram with a yes/no prompt, in parallel with the
  terminal prompt.
- Replies delivered back to the chat.

Out of scope:

- `/settings` and `/tools` from Telegram: both are interactive terminal menus with no
  meaningful remote equivalent. The user explicitly excluded configuration and tools.
- Webhooks, multiple users, group chats, bot administration, media handling, inline
  queries other than the approval buttons.
- Persisting the session, the bot token, or the remote configuration to disk.
- Running the bridge without the terminal session (a headless daemon is a different
  feature).

## 3. Glossary

| Term | Meaning |
|---|---|
| **Bridge** | The set of pieces that connect the Telegram Bot API to the running agent. |
| **Remote line** | A line of text produced by a Telegram message, translated into the same syntax the terminal accepts. |
| **Authorized user** | The single Telegram user whose id matches `PBL_TELEGRAM_USER`. |
| **Session line** | One entry of the queue of pending remote lines, with the chat it came from. |
| **Approval** | A pending request for permission to run a tool that has `confirm: true`. |
| **Transport** | The component that delivers text to a chat and delivers approval requests. In production it is Telegram; in the tests it is a fake. |

## 4. Functional requirements

### FR-1 — `/rc` starts and stops the bridge

- **FR-1.1** `/rc` in the terminal starts the Telegram bridge for the current session.
- **FR-1.2** `/rc` while the bridge is running stops it. The second invocation reports
  that remote control is off.
- **FR-1.3** The bridge is stopped when the session ends.
- **FR-1.4** `/rc` never raises an unhandled exception: a failure to start is reported as a
  message and the REPL keeps working.
- **FR-1.5** The bridge state (on/off) is visible in the terminal right after the command.

### FR-2 — Credentials come from the environment

- **FR-2.1** The bot token is read from the environment variable `PBL_TELEGRAM_API_KEY`.
- **FR-2.2** The authorized user id is read from the environment variable
  `PBL_TELEGRAM_USER`.
- **FR-2.3** Both variables are read **at the moment `/rc` runs**, not at start-up, so a
  user can export them in the same shell session.
- **FR-2.4** If either variable is missing or empty, `/rc` fails with a message naming
  both variables and explaining what they must contain. The bridge does not start.
- **FR-2.5** The token is never written to disk, never printed, and never included in an
  error message.
- **FR-2.6** The token is not read from, nor written to, `~/.pbl`.

### FR-3 — Only the authorized user is served

- **FR-3.1** A message is served only when the sender's id matches `PBL_TELEGRAM_USER`.
- **FR-3.2** `PBL_TELEGRAM_USER` holds the numeric Telegram user id. A value that is not
  a number is treated as a username and compared against the sender's `@username`.
- **FR-3.3** A message from any other sender is **not** executed, **not** answered and
  **not** queued.
- **FR-3.4** A rejected message produces a **red** warning on the terminal stating that
  another user is trying to use the bot and that the API key may be compromised.
- **FR-3.5** The warning does not include the bot token.
- **FR-3.6** The comparison is exact: no prefix, no numeric coercion that would let
  `123` match `1234`.

### FR-4 — Transparency for the agent

- **FR-4.1** A free-text Telegram message is an ordinary turn: the same system prompt, the
  same tools, the same active agent and skills, the same session context.
- **FR-4.2** No extra skill, prompt or system message is introduced by the bridge.
- **FR-4.3** The reply to the chat is the output of that turn, exactly as it is shown in
  the terminal.
- **FR-4.4** The terminal user sees the same turn: a remote turn is not hidden from the
  terminal.
- **FR-4.5** The session context is shared: a turn started from Telegram sees the
  messages exchanged from the terminal, and vice versa.
- **FR-4.6** The session context is only ever mutated by the thread that owns the REPL, so
  a remote turn can never interleave with a local turn.

### FR-5 — Minimal command set from Telegram

- **FR-5.1** The following commands are available from Telegram: `/agent`, `/skills`,
  `/new`, `/compact`, `/help`.
- **FR-5.2** `/settings` and `/tools` are **not** available from Telegram. A request for
  them is answered with a short explanation that they are only available in the terminal.
- **FR-5.3** `/agent` without arguments lists the available agents and which one is
  active. `/agent <name>` activates that agent. `/agent none` deactivates it.
- **FR-5.4** `/skills` without arguments lists the available skills and which ones are
  active. `/skills <a,b>` activates exactly those skills. `/skills none` deactivates all
  of them.
- **FR-5.5** An unknown agent or skill name is reported as an error and changes nothing.
- **FR-5.6** Selecting an agent or a skill from Telegram persists to `config.json`, the
  same way the terminal menu does.
- **FR-5.7** `/new` and `/compact` from Telegram behave exactly like the terminal
  commands, including the automatic-compaction setting.
- **FR-5.8** `/help` returns the list of available commands and states that the session
  is the terminal one.

### FR-6 — Tool approval from Telegram

- **FR-6.1** When the agent asks for permission to run a tool that requires confirmation,
  the request is shown in the terminal **and** sent to the authorized chat with a yes/no
  control.
- **FR-6.2** Either surface can answer: the first answer wins and the other one is
  ignored.
- **FR-6.3** The remote answer is explicit. A remote "no" can never be interpreted as a
  "yes" — the remote protocol does not reuse the terminal's key semantics.
- **FR-6.4** The default is **deny**. A timeout, an interruption, a closed connection or
  any unanswered request denies the tool.
- **FR-6.5** When the request is resolved, the chat is told how it was resolved, so a
  stale button cannot be pressed twice.
- **FR-6.6** A request that is answered in the terminal is reported in the chat as
  resolved elsewhere, and vice versa.
- **FR-6.7** The approval request shows which action is being requested and its preview,
  exactly as the terminal shows it.

### FR-7 — Replies

- **FR-7.1** Every served Telegram message receives exactly one reply.
- **FR-7.2** The reply contains the output of the turn or of the command, without the
  terminal's control characters.
- **FR-7.3** A message that produces no output still gets a reply, so the user is never
  left waiting.
- **FR-7.4** An error during the turn is reported in the reply, not swallowed.

### FR-8 — Lifecycle and robustness

- **FR-8.1** The bridge runs in a background thread; the terminal keeps its responsiveness
  while it is active.
- **FR-8.2** The absence of the Telegram library is not fatal: the application starts and
  works normally, and only `/rc` reports the missing dependency.
- **FR-8.3** A network failure while the bridge is running does not crash the application.
- **FR-8.4** The bridge never writes to the session context on its own; it only asks the
  owning thread to execute a line.

## 5. Non-functional requirements

- **NFR-1** The Telegram library is imported **lazily**: importing the application must
  not require it, and the rest of the application must work without it.
- **NFR-2** The credential and the authorization logic live in modules that can be
  unit-tested without a network and without the Telegram library.
- **NFR-3** The stdin is read by exactly one place at a time: the REPL prompt while it
  waits, the approval menu while it waits. They never overlap.
- **NFR-4** No global state is introduced: the bridge and its queue are owned by the
  session, not by module-level variables.
- **NFR-5** The existing behaviour of the terminal, with the bridge off, is bit-for-bit
  unchanged: same prompts, same keys, same menus.
- **NFR-6** No new dependency is added to the *mandatory* requirements: the Telegram
  library is an optional extra.
- **NFR-7** The whole test suite stays green.

## 6. Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | `/rc` with no credentials reports both variable names and does not start the bridge. | unit test |
| AC-2 | `/rc` with valid credentials starts the bridge and says so. | unit test (fake transport) |
| AC-3 | `/rc` twice stops the bridge. | unit test |
| AC-4 | A message from the authorized id is served. | unit test |
| AC-5 | A message from another id is ignored and prints a red warning. | unit test |
| AC-6 | The warning never contains the token. | unit test |
| AC-7 | A free-text message becomes a normal turn with the same context. | unit test + fake LLM |
| AC-8 | `/agent` lists, `/agent <name>` activates and persists. | unit test |
| AC-9 | `/skills` lists, `/skills a,b` activates and persists. | unit test |
| AC-10 | An unknown agent name changes nothing and reports an error. | unit test |
| AC-11 | `/settings` and `/tools` from Telegram are refused with an explanation. | unit test |
| AC-12 | `/new` and `/compact` work from Telegram. | unit test |
| AC-13 | An approval request reaches the chat with a yes/no control. | unit test |
| AC-14 | Answering "yes" from the chat allows the tool. | unit test + fake LLM |
| AC-15 | Answering "no" from the chat denies the tool. | unit test + fake LLM |
| AC-16 | An unanswered approval denies the tool. | unit test |
| AC-17 | The terminal can still answer an approval that the chat also received. | unit test |
| AC-18 | The remote answer never leaks into the terminal's key semantics. | unit test |
| AC-19 | Every served message gets exactly one reply. | unit test |
| AC-20 | The reply contains no terminal control characters. | unit test |
| AC-21 | The terminal is unaffected when the bridge is off. | existing suite |
| AC-22 | The application starts without the Telegram library installed. | unit test |

## 7. Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `python-telegram-bot` (>= 22) | optional | Standard library for the Telegram Bot API. Python ≥ 3.10, Bot API 10.0, pulls `httpx`. Imported lazily. |
| `session-commands` feature | internal | Provides the `Session` object, `/new` and `/compact`. |
| Telegram bot token | external | Obtained from @BotFather; supplied through `PBL_TELEGRAM_API_KEY`. |
| Telegram user id | external | The numeric id of the owner; supplied through `PBL_TELEGRAM_USER`. |
