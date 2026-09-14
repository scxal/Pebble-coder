# REQUIREMENT: LIGHTWEIGHT REACT AGENT FOR LOCAL MODELS

## Objective

Create a minimalist ReAct agent in Python designed to work efficiently with small and fast models run locally via Ollama or OpenAI API-compatible servers.

The design must prioritize:

- Low latency.
- Simplicity.
- Low context consumption.
- Compatibility with 4B-8B parameter models.
- Minimal JSON tool calling dependency.
- Compatibility with Gemma 4 E4B, Qwen3-Coder 8B, and similar models.
- Ability to switch models without modifying code.

Do not use heavy frameworks such as:

- LangChain
- CrewAI
- AutoGen
- Semantic Kernel

The project must have the fewest possible external dependencies.

---

## Design Philosophy

This agent is intended for home hardware and fast models.

It must prioritize:

- Fast responses.
- Short iterations.
- Small contexts.
- Simple tools.
- Robustness.

Do not attempt to replicate Claude Code, OpenCode, or Cursor.

Do not use:

- MCP
- OpenAI Function Calling
- Multi-level planners
- Dynamic tools
- Complex persistent memory
- Nested agents
- Multi-agent

The philosophy is:

"Fewer tools, more speed."

---

## General Architecture

Classic ReAct pattern:

User
↓
LLM
↓
Thought
↓
Action
↓
Tool Execution
↓
Observation
↓
LLM
↓
...
↓
Final Answer

The model only generates text.

It never executes tools.

The runtime interprets and executes the actions.

---

## Configuration

All configuration must be stored in an external file:

config.json

Example:

```json
{
  "model": "gemma4:e4b",
  "base_url": "http://localhost:11434/v1",
  "temperature": 0.2,
  "max_iterations": 10,
  "timeout": 30,
  "format": "text"
}
```

It must be possible to change:

- model
- endpoint
- temperature
- iteration limit

without modifying code.

Examples of valid models:

```json
{
  "model": "gemma4:e4b"
}
```

```json
{
  "model": "qwen3-coder:8b"
}
```

```json
{
  "model": "phi4-mini"
}
```

---

## System Prompt

Create:

system_prompt.md

Content:

# ReAct Agent

You are a lightweight ReAct agent.

Available tools:

- list_files(path)
- read_file(path)
- write_file(path, content)
- run_command(command)

Rules:

1. Think step by step.
2. Use a single tool per response.
3. Never fabricate observations.
4. Never assume a tool was executed.
5. Wait for Observation before continuing.
6. Keep reasoning concise.
7. Minimize token usage.
8. Prefer exploration before modification.

Output format:

Thought: your reasoning

Action: tool_name

Input: tool arguments

When the task is completed:

Final Answer:
<result>

Example:

Thought: I need to inspect the project.

Action: list_files

Input: .

Observation:
src
package.json

Thought: I should inspect package.json

Action: read_file

Input: package.json

Observation:
{ ... }

Final Answer:
This is a NodeJS project.

---

## Initial Tools

Implement only:

### list_files

Signature:

```python
list_files(path)
```

Description:

Lists files and directories.

---

### read_file

Signature:

```python
read_file(path)
```

Description:

Reads text files.

---

### write_file

Signature:

```python
write_file(path, content)
```

Description:

Overwrites or creates files.

---

### run_command

Signature:

```python
run_command(command)
```

Description:

Executes shell commands.

Must include:

- configurable timeout
- stdout capture
- stderr capture

---

## Parser

Implement parser for:

```text
Thought: I need to inspect the project

Action: list_files

Input: .
```

Extracting:

```python
action = "list_files"
input = "."
```

Use simple regular expressions.

Avoid complex parsers.

---

## Main Loop

Recommended structure:

```python
for iteration in range(max_iterations):
```

Process:

1. Send history to the model.
2. Get response.
3. Look for Final Answer.
4. If it exists, finish.
5. Parse Action.
6. Execute tool.
7. Generate Observation.
8. Continue.

---

## Exit Conditions

Exit when any of these conditions occur:

### Case 1

```text
Final Answer:
```

### Case 2

```python
iteration >= max_iterations
```

### Case 3

Invalid parser.

### Case 4

Non-existent tool.

### Case 5

Critical execution error.

---

## Error Handling

If a tool fails:

```text
Observation:
ERROR: <message>
```

Allow the model to recover.

Do not finish immediately.

---

## Optimization for Gemma 4

Prefer format:

```text
Thought:
Action:
Input:
Observation:
```

Avoid:

```json
{
  "tool_calls": [...]
}
```

Avoid:

```json
{
  "function_call": ...
}
```

Gemma usually performs better with structured text than with Function Calling.

---

## Optional XML Format

A configurable option must exist:

```json
{
  "format": "xml"
}
```

When using XML, the model should respond:

```xml
<thought>
I need to inspect the project.
</thought>

<action>
list_files
</action>

<input>
.
</input>
```

The runtime must parse it.

---

## Tool Limit

Do not initially implement more than:

- list_files
- read_file
- write_file
- run_command

The goal is to keep the context small.

Additional tools must be added manually.

---

## Allowed Dependencies

Preferably:

```text
requests
openai
json
re
pathlib
subprocess
typing
```

Avoid unnecessary dependencies.

---

## Project Structure

```text
project/
│
├── agent.py
├── parser.py
├── tools.py
├── config.json
├── system_prompt.md
├── requirements.txt
└── README.md
```

---

## Quality Requirements

The generated code must:

- Be easy to read.
- Have few files.
- Be extensible.
- Have minimal comments.
- Be able to run immediately after installing dependencies.

---

## Final Goal

Build an extremely lightweight and fast ReAct agent for home hardware.

Target hardware:

- RX 6600 8GB
- 32GB RAM
- Ubuntu Linux

Target models:

- Gemma 4 E4B
- Qwen3-Coder 8B
- Phi 4 Mini
- Other fast 4B-8B models
- Groq-Llama-8B

The absolute priority is:

1. Speed.
2. Robustness.
3. Low token consumption.
4. Simplicity.

Do not pursue advanced agentic capabilities at the expense of latency.
