```
███  ████ ███  ███  █    ████       ███  ██  ███  ████ ███
█  █ █    █  █ █  █ █    █         █    █  █ █  █ █    █  █
███  ███  ███  ███  █    ███  ████ █    █  █ █  █ ███  ███
█    █    █  █ █  █ █    █         █    █  █ █  █ █    █ █
█    ████ ███  ███  ████ ████       ███  ██  ███  ████ █  █
```

# Pebble-coder

Lightweight ReAct Agent for Local Models

Minimalist ReAct agent in Python designed to operate with low latency and low memory consumption on home hardware (for example, 8GB GPUs like RX 6600 or RTX 3060). It works with small and ultra-fast local models (4B-8B parameters) such as **Gemma 4 E4B**, **Qwen 2.5 / 3-Coder 7B/8B**, **Phi 4 Mini** via OpenAI API-compatible servers (Ollama, LM Studio, vLLM, or Groq).

---

## Index

1. [Key Features](#key-features)
2. [Project Structure](#project-structure)
3. [Prerequisites](#prerequisites)
4. [Quick Start Guide](#quick-start-guide)
5. [Text File Configuration Instructions](#text-file-configuration-instructions)
   - [General Configuration (config.json)](#1-general-configuration-configjson)
   - [Visibility Control and Clean Chat Mode (debug, thought, observation)](#visibility-control-and-clean-chat-mode)
   - [Tool Configuration (tools.json)](#2-tool-configuration-toolsjson)
   - [Prompt Customization (system_prompt.md)](#3-prompt-customization-system_promptmd)
   - [Using the Optional XML Format](#4-using-the-optional-xml-format)
6. [Usage Modes](#usage-modes)
   - [Interactive Console Mode (REPL)](#1-interactive-console-mode)
   - [Direct Command Mode (CLI)](#2-direct-command-mode)
   - [Slash Commands and Autocomplete](#3-slash-commands-and-autocomplete)
7. [Available Tools (including web_search with agent-browser)](#available-tools)
8. [Tests (Sanity Tests)](#tests-sanity-tests)
9. [Troubleshooting](#troubleshooting)

---

## Key Features

- **Clean chat by default:** Only shows interactions and responses from the assistant. Internal reasoning (`Thought`) and file read dumps or observations do not flood the screen unless enabled.
- **Organized web search (`web_search`):** Native integration with `agent-browser` to perform concise web searches and page reading without overloading the model context or requiring paid APIs.
- **No heavy frameworks:** Does not use LangChain, CrewAI, AutoGen, or libraries with complex dependencies.
- **No complex Function Calling:** Uses the classic ReAct pattern based on structured text (`Thought / Action / Input / Observation / Final Answer`), ideal for small models that hallucinate or fail with JSON tool calling.
- **100% Configurable without touching code:** Models, endpoints, tools, log visibility, and prompts reside in editable text files (`.json` and `.md`).

---

## Project Structure

```text
react-agent/
│
├── agent.py            # Main ReAct loop, '/' commands, and interactive console
├── parser.py           # Regex-based parser (plain text and XML)
├── tools.py            # Tool implementation (web_search via DDG/Wikipedia APIs)
├── menu.py             # Interactive menu engine (/settings, confirmations, autocompletion)
├── config.json         # General configuration (model, endpoint, visibility flags, etc.)
├── tools.json          # Tool activation, parameters, and confirmation control
├── commands.json       # List of '/' commands for autocompletion
├── translations_es.json# Spanish texts (sections: ui, menu, tools, parser)
├── translations_en.json# English texts (sections: ui, menu, tools, parser)
├── system_prompt.md    # Standard ReAct system prompt (editable)
├── system_prompt_xml.md# Alternative system prompt in XML format
├── requirements.txt    # Python dependencies (only 'requests')
├── run_tests.sh        # Runs the sanity suite
├── tests/              # Test suite (unit + E2E with pty)
├── lineamientos.md     # Technical project specifications
└── README.md           # This instruction guide
```

---

## Prerequisites

1. **Python 3.10 or higher**.
2. **Local AI server:**
   - [Ollama](https://ollama.com/) (recommended for Linux/macOS/Windows).
   - Or [LM Studio](https://lmstudio.ai/), [vLLM](https://github.com/vllm-project/vllm), [LocalAI](https://localai.io/), or any server with an OpenAI-compatible endpoint (`/v1/chat/completions`).
3. **agent-browser:** Navigation and reading tool installed on the system.

---

## Quick Start Guide

### Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 2: Start your local server and download a model

If you use **Ollama**, download and run the desired model:

```bash
# Start the service (if not running as a system service)
ollama serve

# In another terminal, download the model:
ollama pull gemma4:e4b
# or alternatively:
ollama pull qwen2.5-coder:7b
```

---

### Step 3: Start the agent in the console

```bash
python3 agent.py
```

The welcome banner with the configuration status will appear:

```text
============================================================
  Lightweight ReAct Agent for Local Models
============================================================
Model       : gemma4:e4b
Endpoint    : http://localhost:11434/v1
Format      : text
Debug       : off
Thought     : off
Observation : off
Tools       : list_files, read_file, write_file, run_command, web_search
Type '/exit' to exit (commands start with '/').
------------------------------------------------------------

You > 
```

---

## Text File Configuration Instructions

You do not need to recompile or touch any `.py` file to change the agent's behavior.

### 1. General Configuration (`config.json`)

Edit `config.json` with any text editor:

```json
{
  "language": "es",
  "model": "gemma4:e4b",
  "base_url": "http://localhost:11434/v1",
  "api_key": "ollama",
  "temperature": 0.2,
  "max_iterations": 10,
  "timeout": 30,
  "format": "text",
  "debug": "off",
  "thought": "off",
  "observation": "off",
  "system_prompt_file": "system_prompt.md",
  "tools_file": "tools.json"
}
```

#### Available options:

| Key | Type | Values | Description |
|---|---|---|---|
| `language` | string | `"es"`, `"en"` | Interface language (translations files); changing it from `/settings` hot-reloads all texts |
| `model` | string | `"gemma4:e4b"`, etc. | Model name on your local server |
| `base_url` | string | URL | Base URL of the OpenAI-compatible API |
| `api_key` | string | `"ollama"`, etc. | API key if your server requires one |
| `temperature` | float | `0.1` - `0.3` | Randomness in generation (lower values give higher precision in ReAct) |
| `max_iterations` | int | `10` | Maximum cycle limit per query |
| `timeout` | int | `30` | Maximum wait time in seconds per LLM response |
| `format` | string | `"text"` or `"xml"` | Thought and action format |
| `debug` | string/bool | `"on"` / `"off"` | Enables verbose mode with full detailed logging |
| `thought` | string/bool | `"on"` / `"off"` | Shows the model's internal thinking on screen |
| `observation` | string/bool | `"on"` / `"off"` | Shows observation content (file reads, commands) |
| `system_prompt_file` | string | `.md` path | System prompt file |
| `tools_file` | string | `.json` path | Tool configuration file |

---

### Visibility Control and Clean Chat Mode

To prevent the screen from flooding with unnecessary data:

- **Clean Chat Mode (`"debug": "off"`, `"thought": "off"`, `"observation": "off"`):**
  This is the default behavior. The screen only shows your messages and the assistant's final response. If the agent queries a 500-line file or performs a web search, the content is sent internally to the LLM, but not printed in the terminal; you will only see a clean progress notice like `[Reading file: config.json]` or `[Searching the web: ...]`.

- **View only thoughts (`"thought": "on"`):**
  Shows the `[Thought]` block from the model while reasoning, keeping file observations hidden.

- **View tool observations (`"observation": "on"`):**
  Shows the content returned by tool execution (read files, command outputs, web results).

- **Full Debug Mode (`"debug": "on"`):**
  Shows all iterations step by step (`--- [Iteration X/Y] ---`), `[Thought]`, `[Action]`, `[Input]`, full `[Observation]`, and `[Final Answer]`.

---

### 2. Tool Configuration (`tools.json`)

```json
{
  "list_files": {
    "enabled": true,
    "confirm": false,
    "description": "list_files(path) - Lists files and directories in the specified path (default '.')."
  },
  "read_file": {
    "enabled": true,
    "confirm": false,
    "description": "read_file(path) - Reads the text content of a file."
  },
  "write_file": {
    "enabled": true,
    "confirm": true,
    "description": "write_file(path, content) - Overwrites or creates a file with the specified content."
  },
  "run_command": {
    "enabled": true,
    "confirm": true,
    "description": "run_command(command) - Executes system shell commands with stdout and stderr capture.",
    "timeout": 30
  },
  "web_search": {
    "enabled": true,
    "confirm": false,
    "description": "web_search(query) - Searches the web for information on a topic using Wikipedia and DuckDuckGo. Write the query in the same language as the user. If the input is a URL, it directly extracts the content of that page.",
    "timeout": 20,
    "max_output_chars": 3000,
    "max_wiki_results": 4,
    "max_ddg_topics": 3,
    "fetch_budget": 2400,
    "auto_fetch": false
  },
  "web_fetch": {
    "enabled": true,
    "confirm": false,
    "description": "web_fetch(url) - Opens a specific URL (http:// or https://) and returns its readable text. Use it when the user gives a direct link.",
    "timeout": 20,
    "max_output_chars": 3000
  }
}
```

- **To disable a tool:** Change `"enabled": false`. The model will not be able to invoke it.
- **To request user confirmation:** Change `"confirm": true`. Before executing the tool, the agent shows a Yes/No menu (`Esc`, `q`, or `Ctrl+C` deny).
- **`web_search`:** `"timeout"` controls the request seconds (search and URL reading). The optional keys below cap result sizes so small models are not flooded (the system prompt and tool description instruct the model to query in the user's language):
  - `"max_output_chars"`: max characters of the assembled result (default `3000`).
  - `"max_wiki_results"`: max Wikipedia hits (default `4`).
  - `"max_ddg_topics"`: max DuckDuckGo related-topics shown (default `3`).
  - `"fetch_budget"`: max characters distilled from a direct URL (default `2400`, capped by `max_output_chars`).
  - `"auto_fetch"`: when `true` and DuckDuckGo returns **no** abstract, the tool fetches the **full Wikipedia article** of the top hit via the Wikipedia API (no browser) — more reliable than scraped snippets for small models. Falls back to opening the top DuckDuckGo topic URL with `agent-browser`. Default `false`.

---

### 3. Prompt Customization (`system_prompt.md`)

You can open `system_prompt.md` and adapt the instructions, language, or personality of the agent without restarting anything.

---

### 4. Using the Optional XML Format

If your model performs better with XML, in `config.json` change:
```json
{
  "format": "xml",
  "system_prompt_file": "system_prompt_xml.md"
}
```

---

## Usage Modes

### 1. Interactive Console Mode

```bash
python3 agent.py
```

Interaction examples:

```text
You > What are the latest Python 3.12 features?
[Searching the web: Python 3.12 features]

Assistant:
Python 3.12 introduces significant performance improvements, better syntax error messages, the integration of the new parser, and interpreter optimizations...
```

To exit type `/exit` (or press `Ctrl + C`). When typing `/` you will see autocompletion with available commands; `↑/↓` choose, `Enter` executes, `Tab` completes.

### 2. Direct Command Mode

For pipelines or scripts:

```bash
python3 agent.py "Read config.json and tell me which model is selected"
```

---

### 3. Slash Commands and Autocomplete

The console supports commands that start with `/`:

- **`/settings`**: opens the interactive settings menu (explained below).
- **`/exit`** (alias `/quit`): closes the agent.
- **Autocomplete:** when you type `/` a popup shows the available commands and their descriptions, filtered as you type. `↑/↓` selects, `Enter` executes, `Tab` completes, `Esc` opens/closes the list.
- **Line editing:** the block cursor marks where input goes: `←/→` move it, text is inserted at it, `Backspace` deletes before it, `Delete` deletes at it, `Home`/`End` jump to the start/end of the line.

The command list lives in `commands.json` (command name → i18n key of its description).

#### The `/settings` menu

Each option maps to one `config.json` key and shows its current value:

- Navigate with `↑/↓` or press the option number (`1-9`). `Enter` edits/toggles, `q` or `Esc` closes the menu.
- **Toggles** (`debug`, `thought`, `observation`) flip instantly. **Choices** (`language`, `format`) cycle between their valid values. **Text options** (`model`, `base_url`, `api_key`, `temperature`, `max_iterations`, `timeout`, `system_prompt_file`, `tools_file`) open an input line with validation: an invalid value is rejected and nothing changes.
- Every change applies live to the running session **and** is saved to `config.json` immediately, so no restart is needed.
- Changing `language` hot-reloads all interface texts without restarting.
- Changing `tools_file` reloads the tool configuration on the spot.

---

## Available Tools

1. **`web_search(query)`** *(the only research tool)*:
   - Queries **DuckDuckGo (Instant Answers) and Wikipedia APIs** in the language configured in `config.json` — without a browser, without paid APIs, and without scraping that search engines block.
   - Returns a direct summary of the topic plus structured results (title, snippet, and URL) compact for small models.
   - If the query is a URL (starts with `http://` or `https://`), it directly extracts and distills the page content with `agent-browser`.
   - Strictly limits length to avoid overloading the context of small models (4B-8B).

2. **`list_files(path)`**:
   - Lists files and folders of the indicated directory sorted by size.

3. **`read_file(path)`**:
   - Reads UTF-8 text files with safe truncation if it exceeds context limits.

4. **`write_file(path, content)`**:
   - Creates or overwrites files automatically creating intermediate folders.

5. **`run_command(command)`**:
   - Executes system commands with a time limit (`timeout`) and `stdout`/`stderr` capture.

6. **`web_fetch(url)`**:
   - Opens ONE specific URL (`http://`/`https://`) and returns its readable text via `agent-browser`, capped by `max_output_chars`.
   - Use case: the user provides a direct link or a page must be read in full (complements `web_search`).

---

## Tests (Sanity Tests)

The suite verifies that the agent is not broken: parser, helpers, `web_search`, UTF-8 accented input (`áéíóúñ`/`ÁÉÍÓÚÑÜ` in the REPL), and real E2E flows (`/settings` menu, tool confirmations, and command autocompletion) by running `agent.py` in a pty with a simulated LLM.

```bash
./run_tests.sh          # full suite
./run_tests.sh -v       # detailed output
./run_tests.sh -k test_confirm   # only one group
```

- Does not require your local LLM server: E2E flows use a fake SSE server with scripted responses.
- `config.json` is backed up and automatically restored after each test.
- Network tests (`web_search`) are skipped automatically if there is no internet connection.
- Approximate full suite time: 1-2 minutes.

---

## Troubleshooting

### Error: `Could not connect to LLM endpoint`
- Verify that Ollama is running: `curl http://localhost:11434/api/tags`.
- If you use another port, configure it in `"base_url"` within `config.json`.

### Error: `'agent-browser' tool is not installed or not found in PATH`
- Make sure `agent-browser` is accessible in your `$PATH` or in `~/.local/share/pi-node/.../bin`.

### I want to see step by step what the model does
- Enable `"debug": "on"` in `config.json` to see the full ReAct cycle.
