# Requirements — Session commands (`/new`, `/compact`) and automatic compaction

- **Feature id:** `session-commands`
- **Status:** approved (2026-10-22)
- **Phase:** 1 of 2 (prerequisite of the `telegram-bridge` feature, which must expose both commands)

## 1. Context

Pebble-Coder keeps a *session history*: the list of `{"role", "content"}` messages that
precede the current turn when the request is built (`agent.py:482-485`). Today that history
is a plain list owned by `main()` and trimmed to the last 3 exchanges
(`_HISTORY_MAX_MESSAGES = 6`, `agent.py:449`). There is no way to drop it and no way to
shrink it, so:

- a user cannot start over without restarting the process;
- a long session cannot be condensed, and the request eventually grows past the model's
  context window.

The Telegram bridge (`telegram-bridge` feature) must be able to drive the *same* session
from a phone. It therefore needs `/new` and `/compact` to exist as first-class session
operations, not as Telegram-only tricks. This feature therefore lands **first**.

## 2. Scope

In scope:

- `/new` — clear the session context and continue with a fresh one.
- `/compact` — summarize the current context into a condensed form and continue.
- Automatic compaction, triggered when the context usage crosses a configurable threshold
  (default 85%).
- Two new `/settings` rows to control the automatic behaviour.
- The plumbing required for the Telegram bridge to reuse these operations.

Out of scope (handled by the `telegram-bridge` feature):

- Any remote-control surface, bot, or approval flow.
- Persisting the session across process restarts (history remains in memory only).
- Editing the compaction prompt by the user.

## 3. Glossary

| Term | Meaning |
|---|---|
| **Session context** | The in-memory list of prior `user`/`assistant` messages sent to the model. |
| **Turn** | One user input plus the assistant's final answer. |
| **Context usage** | How much of the model's context window the outgoing request occupies. Exact (`prompt_tokens` reported by the server) when available, otherwise a `chars/4` estimate. |
| **Context window** | `context_window` from `config.json` (default 32768). Today it is only used for the status bar. |
| **Compaction** | Replacing the session context with a summary of itself. |
| **Autocompact** | Compaction performed automatically, without the user asking. |

## 4. Functional requirements

### FR-1 — `/new` clears the context

- **FR-1.1** `/new` removes every message from the session context.
- **FR-1.2** The next turn is sent to the model with **no** prior messages (only the system
  prompt and the new user message).
- **FR-1.3** `/new` does **not** change the active agent, the active skills, the tools, or
  any setting: those are configuration, not context.
- **FR-1.4** `/new` prints a short confirmation in the user's language.
- **FR-1.5** `/new` on an already-empty context is a no-op that still prints the confirmation.
- **FR-1.6** `/new` is not recorded in the session context.

### FR-2 — `/compact` summarizes the context

- **FR-2.1** `/compact` replaces the session context with a condensed representation of
  itself: one `user` message holding the summary, followed by one `assistant` message
  acknowledging it. The alternating `user`/`assistant` structure is preserved.
- **FR-2.2** The summary is produced by the same model configured in `config.json`, using a
  dedicated summarization instruction. The base ReAct system prompt is **not** used for the
  summary call, and the summary call is **not** parsed as a ReAct response.
- **FR-2.3** The summarization call is invisible to the session context: it is never
  appended to the history and never appears as a turn.
- **FR-2.4** The summarization call does not perturb the status bar (token counters).
- **FR-2.5** If the session context is empty, `/compact` performs no call and reports that
  there is nothing to compact.
- **FR-2.6** If the summarization call fails (connection, timeout, invalid response), the
  session context is left **unchanged** and the error is reported. A failed compaction never
  destroys context.
- **FR-2.7** `/compact` prints a short confirmation in the user's language.

### FR-3 — Automatic compaction

- **FR-3.1** After every turn, the application measures the context usage of the last
  request and compares it with the context window.
- **FR-3.2** When the ratio is **greater than or equal to** the configured threshold, the
  session context is compacted exactly as `/compact` would (FR-2).
- **FR-3.3** The threshold is expressed as a percentage in the range 1-100; default 85.
- **FR-3.4** Automatic compaction can be enabled and disabled independently of the manual
  command.
- **FR-3.5** Automatic compaction is silent unless it actually happens; it never prints a
  message when the threshold is not reached.
- **FR-3.6** Automatic compaction never runs when the session context is empty.
- **FR-3.7** A failing automatic compaction does not abort the turn that triggered it; the
  error is reported and the context is left unchanged (same rule as FR-2.6).
- **FR-3.8** Automatic compaction must not run in an infinite loop: after a compaction the
  next check happens only on the following turn.

### FR-4 — Configuration

- **FR-4.1** `config.json` gains `autocompact` (`"on"` / `"off"`, default `"on"`) and
  `autocompact_threshold` (integer 1-100, default `85`).
- **FR-4.2** Both keys are optional: a configuration file without them behaves as if the
  defaults were present.
- **FR-4.3** Booleans are read with the same semantics as every other switch in the
  application (`is_enabled()`): `"on"`, `"true"`, `"yes"`, `"1"` and `"enabled"` are true.
- **FR-4.4** The threshold is validated as an integer in 1-100; a value outside the range is
  rejected by the editor and the previous value is kept.

### FR-5 — Settings UI

- **FR-5.1** `/settings` exposes one row for the automatic-compaction switch and one row for
  the threshold.
- **FR-5.2** Both rows are appended **after** the existing rows, so the position of the
  currently reachable rows (selected with the digit keys 1-9) does not change.
- **FR-5.3** Changing either row persists immediately to `config.json`.

### FR-6 — Command registration and discoverability

- **FR-6.1** `/new` and `/compact` are dispatched by the same mechanism as the existing
  commands.
- **FR-6.2** Both appear in the autocomplete popup with a translated description, in both
  supported languages.
- **FR-6.3** The list of known commands shown in the "unknown command" error message
  includes them.
- **FR-6.4** The popup still shows the exit command after the list grows.

### FR-7 — Existing installations

- **FR-7.1** An installation whose `config.json`, `commands.json` or translation files
  already exist receives the new keys **without losing the user's values**.
- **FR-7.2** Missing keys are added with the default value; existing keys are never
  overwritten.
- **FR-7.3** The merge is applied to the translation files section by section, so a user's
  custom translation of an existing key survives.

### FR-8 — Internationalization

- **FR-8.1** Every new user-visible string exists in both `translations_es.json` and
  `translations_en.json`, with identical key sets.
- **FR-8.2** A missing key never renders as an empty label: the application falls back to
  the Spanish text, and if that is missing too, to a non-empty built-in default.

## 5. Non-functional requirements

- **NFR-1** The session context stays in memory only; no new file is written for it.
- **NFR-2** The compaction call reuses the configured model, endpoint, API key and timeout.
- **NFR-3** No new third-party dependency is introduced by this feature.
- **NFR-4** The existing behaviour of every other command is unchanged.
- **NFR-5** The whole test suite stays green.

## 6. Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | `/new` empties the session context and the next request carries no prior message. | unit test |
| AC-2 | `/new` leaves the active agent and skills untouched. | unit test |
| AC-3 | `/compact` replaces the context with a summary pair and shrinks it. | unit test with a fake LLM |
| AC-4 | The compaction request is not part of the session context. | unit test |
| AC-5 | A failing compaction leaves the context untouched. | unit test with a failing LLM |
| AC-6 | `/compact` on an empty context makes no LLM call. | unit test |
| AC-7 | Context usage at or above the threshold triggers compaction automatically. | unit test |
| AC-8 | Context usage below the threshold does not. | unit test |
| AC-9 | The threshold is configurable and persisted. | unit test |
| AC-10 | The two new rows appear in `/settings` and persist. | unit test + E2E |
| AC-11 | Both commands appear in the popup and in the unknown-command message. | E2E |
| AC-12 | An existing installation gains the new config and translation keys without losing values. | unit test |
| AC-13 | Both languages expose the same key sets. | existing parity test |

## 7. Dependencies

- None external. The feature is a prerequisite of `telegram-bridge`, which reuses `/new`
  and `/compact` and the same session object.
