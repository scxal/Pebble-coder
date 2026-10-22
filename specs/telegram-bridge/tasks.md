# Tasks — Telegram bridge (remote control of Pebble-Coder)

- **Feature id:** `telegram-bridge`
- **Spec:** `specs/telegram-bridge/requirements.md`, `specs/telegram-bridge/design.md`
- **Prerequisite:** `specs/session-commands/` (done — `Session`, `/new` and `/compact` exist)
- **Rule:** tasks are executed in order; every task ends with the suite green.

## Legend

- [ ] pending · [x] done
- **Files** lists every file the task touches.
- **Done when** is the check that closes the task.

---

## TG-1 — `remote.py`: the queue of remote lines

- [ ] **TG-1.1** Create `remote.py` with the `RemoteTransport` interface (`send_text`,
      `send_approval`, `resolve_approval`).
- [ ] **TG-1.2** Add `SessionLine` (text + target chat).
- [ ] **TG-1.3** Add `RemoteController` with `set_transport`, `clear_transport`,
      `enabled`, `push`, `poll_text`, `current_target`, `current_line` and `send`.
- [ ] **TG-1.4** Use `queue.Queue` so the producer (bridge thread) and the consumer
      (REPL thread) have a memory barrier.
- **Files:** `remote.py` (new)
- **Done when:** `python3 -c "import remote"` succeeds and the module imports nothing
  from the project and nothing from third parties.

## TG-2 — `remote.py`: the approval broker

- [ ] **TG-2.1** Add `_PendingApproval` (id, action, preview, deadline, decision).
- [ ] **TG-2.2** Add `ApprovalBroker` with `begin`, `poll`, `settle`, `end`,
      `resolve_remote` and `enabled`.
- [ ] **TG-2.3** `poll()` returns the remote decision when there is one and `False`
      (deny) once the deadline has passed.
- [ ] **TG-2.4** `resolve_remote()` only accepts the id of the current pending request.
- [ ] **TG-2.5** `settle()` notifies the transport so the chat can update the message.
- **Files:** `remote.py`
- **Done when:** a broker that nobody answers denies the request, and a stale id is
  rejected.

## TG-3 — `remote.py`: capturing the output for the reply

- [ ] **TG-3.1** Add `capture_stdout()`, a context manager that tees `sys.stdout` into a
      `StringIO` while still writing to the original stream.
- [ ] **TG-3.2** Add `strip_ansi(text)` that removes the terminal control sequences.
- [ ] **TG-3.3** Add a helper that drops the lines that become empty after the strip
      (the statistics bar writes cursor movements).
- **Files:** `remote.py`
- **Done when:** the captured text contains the printed output and no escape sequences.

## TG-4 — `menu.py`: the `poll` seam for the menus

- [ ] **TG-4.1** `_read_key(fd, quit_chars, timeout=None)`: with a timeout, wait at most
      that long for a byte and return `None` when nothing arrives.
- [ ] **TG-4.2** `run_menu(title, items, hint=None, poll=None)`: consult the poll when no
      key arrives and return its value, closing the menu.
- [ ] **TG-4.3** `confirm(title, yes_label=None, no_label=None, poll=None)`: return the
      external decision when there is one, the terminal's answer otherwise.
- [ ] **TG-4.4** Check that with `poll=None` the behaviour is unchanged (blocking read,
      same key semantics, `Enter` on the default row is still *Yes*).
- **Files:** `menu.py`
- **Done when:** the existing confirmation tests pass unchanged and a poll hook can
  resolve a menu.

## TG-5 — `menu.py`: the `poll` seam for the REPL prompt

- [ ] **TG-5.1** `command_input(..., poll=None)`: while waiting, consult the poll and
      return the remote text.
- [ ] **TG-5.2** Keep the statistics bar cadence (`_STATUS_TICK`) even though the select
      timeout drops to `_POLL_INTERVAL` when a poll is present.
- [ ] **TG-5.3** Only take a remote line when the local buffer is empty: a half-typed
      local line is never discarded.
- **Files:** `menu.py`
- **Done when:** the prompt still works with no poll, and returns the remote text when
  the poll provides one.

## TG-6 — `session.py`: the remote handles

- [ ] **TG-6.1** Add the optional attributes `remote` and `approvals` to `Session`,
      defaulting to `None`, without importing `remote.py` (duck typing).
- **Files:** `session.py`
- **Done when:** `Session()` still works with no remote feature present.

## TG-7 — `agent.py`: the command contract and the non-interactive commands

- [ ] **TG-7.1** `handle_command(..., args="")`: compute the remainder of the line and
      forward it to the handler.
- [ ] **TG-7.2** Add the `args` parameter to every command handler.
- [ ] **TG-7.3** `cmd_agent(..., args="")`: with arguments, activate an agent by name,
      deactivate it with `none`, or list them with `list`; persist with `save_config`.
- [ ] **TG-7.4** `cmd_skills(..., args="")`: with arguments, activate a comma-separated
      list of skills, deactivate them with `none`, or list them with `list`.
- [ ] **TG-7.5** An unknown agent or skill name reports an error and changes nothing.
- **Files:** `agent.py`
- **Done when:** the interactive menus still work and the argument forms behave.

## TG-8 — `agent.py`: the dual approval

- [ ] **TG-8.1** Add `request_approval(action, preview, broker=None)`.
- [ ] **TG-8.2** Use it in the approval block of `run_react_agent`.
- [ ] **TG-8.3** With no broker the behaviour is exactly the current one.
- **Files:** `agent.py`
- **Done when:** the existing confirmation tests pass unchanged.

## TG-9 — `agent.py`: the REPL loop and the remote branch

- [ ] **TG-9.1** Extract the body of the REPL loop into `dispatch_line(user_input)`.
- [ ] **TG-9.2** Wire `remote.poll_text` into `command_input` and
      `remote.current_target` into the loop.
- [ ] **TG-9.3** A remote line is executed with `capture_stdout()` and the captured text
      is sent back to the chat.
- [ ] **TG-9.4** A remote line can never end the session (the exit check stays local).
- [ ] **TG-9.5** `main()` creates the `RemoteController` and the `ApprovalBroker` and
      attaches them to the `Session`.
- **Files:** `agent.py`
- **Done when:** the local REPL behaves exactly as before.

## TG-10 — `agent.py`: the `/rc` command

- [ ] **TG-10.1** Implement `cmd_rc(config, tools_config, session=None, args="")`:
      start the bridge, or stop it when it is already running.
- [ ] **TG-10.2** Register `/rc` in `COMMANDS`, in `defaults/commands.json` and in the
      fallback list of `load_commands()`.
- [ ] **TG-10.3** Add the `ui` translations (`rc_started`, `rc_stopped`, `rc_unauthorized`,
      `rc_unavailable`, `rc_missing_dependency`, `rc_yes`, `rc_no`, `rc_refused`,
      `rc_help`) in both languages.
- [ ] **TG-10.4** `/rc` never raises: every failure is reported as a message.
- **Files:** `agent.py`, `defaults/commands.json`, `defaults/translations_es.json`,
  `defaults/translations_en.json`
- **Done when:** `/rc` without credentials reports both variable names.

## TG-11 — `telegram_bridge.py`: the pure parts

- [ ] **TG-11.1** Create `telegram_bridge.py` with `API_KEY_ENV`, `USER_ENV` and
      `read_credentials(env=None)` returning `(token, user, error)`.
- [ ] **TG-11.2** Add `is_authorized(user_id, expected)` with the numeric and the
      username rules.
- [ ] **TG-11.3** Add `translate_message(text)` returning `(kind, payload)` for every
      command form, including the `@botname` suffix.
- [ ] **TG-11.4** Add the red warning for an unauthorized sender, written to the
      original stdout and without the token.
- **Files:** `telegram_bridge.py` (new)
- **Done when:** the module imports without `python-telegram-bot` installed.

## TG-12 — `telegram_bridge.py`: the bridge itself

- [ ] **TG-12.1** Implement `TelegramBridge` with `start`, `stop` and the three
      `RemoteTransport` methods.
- [ ] **TG-12.2** Run the bot in a daemon thread with its own event loop, driving
      `initialize()` / `start_polling()` / `shutdown()` by hand so it can be stopped.
- [ ] **TG-12.3** Add the text handler, the help handler and the callback handler; the
      callback data carries the request id.
- [ ] **TG-12.4** `send_approval` sends the action, the preview and an inline keyboard
      with the yes/no buttons.
- [ ] **TG-12.5** Add `start_bridge(controller, broker)` returning `(ok, error)`.
- [ ] **TG-12.6** Every call to the bot from another thread goes through
      `asyncio.run_coroutine_threadsafe`.
- **Files:** `telegram_bridge.py`
- **Done when:** the bridge can be started and stopped without raising.

## TG-13 — dependency and installation

- [ ] **TG-13.1** Add `python-telegram-bot>=22,<23` to `requirements.txt` as an optional
      extra, documented in the README.
- [ ] **TG-13.2** Keep the import lazy: the application must start without the library.
- **Files:** `requirements.txt`, `README.md`
- **Done when:** the application starts and the suite passes with the library absent.

## TG-14 — tests

- [ ] **TG-14.1** `tests/test_remote.py` — the controller queue, the broker, the stdout
      capture and `strip_ansi`.
- [ ] **TG-14.2** `tests/test_telegram_bridge.py` — the credentials, the authorization and
      the message translation (no network, no library).
- [ ] **TG-14.3** `tests/test_remote_flow.py` — the integration tests with a fake
      transport and the fake LLM: a remote turn, `/agent`, `/skills`, `/new`, `/compact`,
      the approvals answered from the "chat", the denial and the stale button.
- [ ] **TG-14.4** Update the assertions that enumerate the known commands
      (`/rc` is now one of them).
- **Files:** `tests/test_remote.py` (new), `tests/test_telegram_bridge.py` (new),
  `tests/test_remote_flow.py` (new), `tests/test_commands.py`,
  `tests/test_settings_menu.py`
- **Done when:** every acceptance criterion of `requirements.md` §6 is covered by a test.

## TG-15 — documentation

- [ ] **TG-15.1** `README.md` — document `/rc`, the two environment variables, the
      remote command set and the optional dependency.
- [ ] **TG-15.2** `CONTEXT.md` — add the change-history entry and update the file map.
- **Files:** `README.md`, `CONTEXT.md`
- **Done when:** the docs match the behaviour.

## TG-16 — final verification

- [ ] **TG-16.1** `./run_tests.sh` — the whole suite is green.
- [ ] **TG-16.2** `./run_tests.sh` with `python-telegram-bot` **not** installed — still
      green (the library is optional).
- [ ] **TG-16.3** Manual acceptance with a real bot: `/rc` connects, a message from the
      phone runs a turn, the approval buttons work, and a message from a foreign account
      produces the red warning on the terminal.
