# Tasks — Session commands (`/new`, `/compact`) and automatic compaction

- **Feature id:** `session-commands`
- **Spec:** `specs/session-commands/requirements.md`, `specs/session-commands/design.md`
- **Rule:** tasks are executed in order; every task ends with the suite green.

## Legend

- [ ] pending · [x] done
- **Files** lists every file the task touches.
- **Done when** is the check that closes the task.

---

## SC-1 — `session.py`: the session object

- [x] **SC-1.1** Create `session.py` with `HISTORY_MAX_MESSAGES = 6` and
      `update_history(history, user_input, answer)` (moved verbatim from `agent.py`).
- [x] **SC-1.2** Add `class Session` with `history`, `is_empty()`, `clear()`, `add()`,
      `transcript()`, `replace()` and `summarize(llm, config)`.
- [x] **SC-1.3** Add the `_COMPACT_SYSTEM` instruction constant.
- **Files:** `session.py` (new)
- **Done when:** `python3 -c "import session"` succeeds and the module imports nothing from
  the project (leaf module).

## SC-2 — `agent.py`: re-export the history primitives

- [x] **SC-2.1** Import `Session`, `update_history` and
      `HISTORY_MAX_MESSAGES as _HISTORY_MAX_MESSAGES` from `session.py`.
- [x] **SC-2.2** Delete the now-duplicated `update_history` and `_HISTORY_MAX_MESSAGES`
      definitions from `agent.py`, keeping the public names importable from `agent`.
- [x] **SC-2.3** `main()` creates `session = Session()` and passes `session.history` to
      `run_react_agent` instead of the local `history` list.
- **Files:** `agent.py`
- **Done when:** `from agent import update_history, _HISTORY_MAX_MESSAGES` still works and
  `tests/test_history.py` passes.

## SC-3 — `agent.py`: `call_llm` statistics switch

- [x] **SC-3.1** Add the `track_stats: bool = True` parameter to `call_llm` and guard the
      `statistics.note_usage(...)` call with it.
- **Files:** `agent.py`
- **Done when:** `call_llm(messages, config, track_stats=False)` does not change the
  statistics counters.

## SC-4 — `agent.py`: the command handler contract

- [x] **SC-4.1** Add the optional `session=None` parameter to `cmd_settings`, `cmd_tools`,
      `cmd_editor`, `cmd_agent`, `cmd_skills` and to `handle_command`, forwarding it to
      the handler.
- [x] **SC-4.2** Verify `tests/test_skills.py` (which calls `handle_command` with two
      arguments) still passes.
- **Files:** `agent.py`
- **Done when:** the suite is green and the handler contract is uniform.

## SC-5 — `agent.py`: `/new` and `/compact`

- [x] **SC-5.1** Implement `cmd_new(config, tools_config, session=None)`.
- [x] **SC-5.2** Implement `apply_compaction(session, config) -> bool` (shared by the manual
      command and the automatic trigger) and `cmd_compact(...)`.
- [x] **SC-5.3** Implement `autocompact_threshold(config)` and
      `should_autocompact(config, ctx_tokens)`.
- [x] **SC-5.4** Wire the automatic trigger into the session turn wrapper: after the turn
      is recorded, evaluate `should_autocompact(config, statistics.last_ctx() or 0)` and
      compact when it holds.
- [x] **SC-5.5** Register `"/new"` and `"/compact"` in the `COMMANDS` dict, in
      `defaults/commands.json` and in the fallback list of `load_commands()`.
- **Files:** `agent.py`, `defaults/commands.json`
- **Done when:** `/new` empties the context, `/compact` replaces it with a summary, and
  neither appears in the history.

## SC-6 — `agent.py`: the settings rows

- [x] **SC-6.1** Add `_validate_percentage(raw)` (integer, 1-100).
- [x] **SC-6.2** Append the `autocompact` toggle row and the `autocompact_threshold` text
      row after the `theme` row in `build_settings_items()`.
- **Files:** `agent.py`
- **Done when:** both rows show up in `/settings` and persist to `config.json`.

## SC-7 — `pbl_home.py`: upgrade existing installations

- [x] **SC-7.1** Implement `sync_defaults()` merging missing keys from `defaults/` into the
      home `config.json`, `commands.json`, `translations_es.json` and
      `translations_en.json`, without overwriting existing values.
- [x] **SC-7.2** Call it from `bootstrap()` after the copy step; write a file only when
      something was actually added.
- **Files:** `pbl_home.py`
- **Done when:** a home with an old `config.json` gains `autocompact` and
  `autocompact_threshold` while keeping the user's values.

## SC-8 — data files and translations

- [x] **SC-8.1** Add `autocompact` and `autocompact_threshold` to `defaults/config.json`.
- [x] **SC-8.2** Add the twelve new `ui` keys to `defaults/translations_es.json` and
      `defaults/translations_en.json` with identical key sets.
- [x] **SC-8.3** Raise `menu._POPUP_MAX` from 8 to 10.
- **Files:** `defaults/config.json`, `defaults/translations_es.json`,
  `defaults/translations_en.json`, `menu.py`
- **Done when:** the translation parity test passes and the popup still shows the exit
  command.

## SC-9 — update the existing tests

- [x] **SC-9.1** `tests/test_commands.py:107` — expected unknown-command string becomes
      `"/settings, /tools, /editor, /agent, /skills, /new, /compact, /exit, /quit"`.
- [x] **SC-9.2** `tests/test_commands.py:61-77` — two extra `↓` presses to reach `/exit`.
- [x] **SC-9.3** `tests/test_settings_menu.py:105` — same string as SC-9.1.
- **Files:** `tests/test_commands.py`, `tests/test_settings_menu.py`
- **Done when:** the suite is green.

## SC-10 — new tests

- [x] **SC-10.1** `tests/test_session.py` — `Session` unit tests: `clear`, `add` trimming,
      `transcript`, `summarize` (fake LLM), `replace`.
- [x] **SC-10.2** `tests/test_session.py` — `/new` clears the context and leaves agent and
      skills untouched.
- [x] **SC-10.3** `tests/test_session.py` — `/compact` replaces the context with the summary
      pair; the compaction request never reaches the history; a failing LLM leaves the
      context untouched; an empty context makes no call.
- [x] **SC-10.4** `tests/test_session.py` — `should_autocompact` is true at and above the
      threshold and false below it; the switch disables it.
- [x] **SC-10.5** `tests/test_session.py` — `pbl_home.sync_defaults()` adds the missing
      keys and keeps the user's values.
- [x] **SC-10.6** `tests/test_settings_menu.py` — the two new rows persist.
- **Files:** `tests/test_session.py` (new), `tests/test_settings_menu.py`
- **Done when:** every acceptance criterion of `requirements.md` §6 is covered by a test.

## SC-11 — documentation

- [x] **SC-11.1** `README.md` — document `/new`, `/compact`, the two new configuration keys.
- [x] **SC-11.2** `CONTEXT.md` — add the change-history entry and update the file map.
- **Files:** `README.md`, `CONTEXT.md`
- **Done when:** the docs match the behaviour.

## SC-12 — final verification

- [x] **SC-12.1** `./run_tests.sh` — the whole suite is green.
- [x] **SC-12.2** Manual check: `/new` then a question ⇒ the model receives no prior
      message; `/compact` then a question ⇒ the model receives the summary.
- [x] **SC-12.3** Manual check: a home directory with an old `config.json` is upgraded on
      start without losing values.
