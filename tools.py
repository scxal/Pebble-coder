import json
import os
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

MAX_OUTPUT_CHARS = 3000
MAX_READ_LINES = 300


def find_agent_browser() -> Optional[str]:
    p = shutil.which("agent-browser")
    if p:
        return p
    known_paths = [
        "/home/sandia/.local/share/pi-node/node-v22.23.2-linux-x64/bin/agent-browser",
        os.path.expanduser("~/.local/bin/agent-browser"),
        "/usr/local/bin/agent-browser",
        "/usr/bin/agent-browser",
    ]
    for kp in known_paths:
        if os.path.isfile(kp) and os.access(kp, os.X_OK):
            return kp
    return None


def list_files(path: str = ".") -> str:
    cleaned_path = path.strip().strip("'\"") or "."
    target = Path(cleaned_path).resolve()
    if not target.exists():
        return f"ERROR: Path does not exist: {cleaned_path}"
    if not target.is_dir():
        return f"ERROR: Path is not a directory: {cleaned_path}"

    try:
        entries = sorted(list(target.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        if not entries:
            return "(empty directory)"

        lines = []
        for entry in entries[:100]:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    lines.append(f"{entry.name} ({size_str})")
                except Exception:
                    lines.append(entry.name)

        if len(entries) > 100:
            lines.append(f"... ({len(entries) - 100} more items omitted)")

        return "\n".join(lines)
    except PermissionError:
        return f"ERROR: Permission denied accessing {cleaned_path}"
    except Exception as exc:
        return f"ERROR: Could not list directory {cleaned_path}: {exc}"


def read_file(path: str) -> str:
    cleaned_path = path.strip().strip("'\"")
    if not cleaned_path:
        return "ERROR: File path cannot be empty"

    target = Path(cleaned_path).resolve()
    if not target.exists():
        return f"ERROR: File not found: {cleaned_path}"
    if target.is_dir():
        return f"ERROR: '{cleaned_path}' is a directory, use list_files instead"

    try:
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            content = target.read_text(encoding="latin-1", errors="replace")

        lines = content.splitlines()
        if len(lines) > MAX_READ_LINES:
            truncated = "\n".join(lines[:MAX_READ_LINES])
            return f"{truncated}\n\n[WARNING: Truncated to first {MAX_READ_LINES} lines]"

        if len(content) > MAX_OUTPUT_CHARS:
            return content[:MAX_OUTPUT_CHARS] + f"\n\n[WARNING: Output truncated to {MAX_OUTPUT_CHARS} characters]"

        return content if content else "(empty file)"
    except PermissionError:
        return f"ERROR: Permission denied reading {cleaned_path}"
    except Exception as exc:
        return f"ERROR: Failed reading file {cleaned_path}: {exc}"


def write_file(path: str, content: str) -> str:
    cleaned_path = path.strip().strip("'\"")
    if not cleaned_path:
        return "ERROR: File path cannot be empty"

    try:
        target = Path(cleaned_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"File '{cleaned_path}' written successfully ({len(content)} characters)."
    except PermissionError:
        return f"ERROR: Permission denied writing to {cleaned_path}"
    except Exception as exc:
        return f"ERROR: Failed writing to file {cleaned_path}: {exc}"


def run_command(command: str, timeout: int = 30) -> str:
    command = command.strip()
    if not command:
        return "ERROR: Command cannot be empty"

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode != 0:
            parts = [f"Exit code: {proc.returncode}"]
            if stdout:
                parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                parts.append(f"STDERR:\n{stderr}")
            result = "\n".join(parts)
        else:
            if stdout and stderr:
                result = f"{stdout}\n[STDERR]:\n{stderr}"
            elif stdout:
                result = stdout
            elif stderr:
                result = f"[STDERR]:\n{stderr}"
            else:
                result = "(Command executed successfully with no output)"

        if len(result) > MAX_OUTPUT_CHARS:
            result = result[:MAX_OUTPUT_CHARS] + f"\n\n[WARNING: Output truncated to {MAX_OUTPUT_CHARS} characters]"

        return result
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout} seconds"
    except Exception as exc:
        return f"ERROR: Failed executing command: {exc}"


def _run_browser(bin_path: str, args: list, timeout: int) -> str:
    """Ejecuta agent-browser con un comando y devuelve stdout (o '' si falla)."""
    try:
        proc = subprocess.run(
            [bin_path] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        return ""
    except (subprocess.TimeoutExpired, Exception):
        return ""


def _browser_get_text(bin_path: str, selector: str, timeout: int) -> str:
    """Extrae el texto de un selector de la pagina activa del navegador."""
    return _run_browser(bin_path, ["get", "text", selector], timeout)


def web_search(query: str, timeout: int = 20, max_results: int = 4) -> str:
    query = query.strip().strip("'\"")
    if not query:
        return "ERROR: Search query cannot be empty"

    bin_path = find_agent_browser()
    if not bin_path:
        return "ERROR: 'agent-browser' tool is not installed or not found in PATH."

    # Si el input es una URL directa, extraer el texto de la pagina
    if query.startswith("http://") or query.startswith("https://"):
        if _run_browser(bin_path, ["open", query, "--timeout", str(timeout * 1000)], timeout + 5):
            text = _browser_get_text(bin_path, "main", timeout)
            return text[:2500] if text else "(Page content is empty)"
        return "ERROR: Could not open URL"

    # Busqueda web con Bing (Yahoo suele bloquear el acceso automatizado)
    search_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    if _run_browser(bin_path, ["open", search_url, "--timeout", str(timeout * 1000)], timeout + 5):
        text = _browser_get_text(bin_path, "main", timeout)
        if text:
            return f"Search results for: \"{query}\"\n\n{text[:4000]}"

    return f"No relevant search results found for '{query}'."


def parse_write_file_args(raw_input: str) -> Tuple[str, str]:
    raw_input = raw_input.strip()

    # 1. JSON parsing
    if raw_input.startswith("{") and raw_input.endswith("}"):
        try:
            data = json.loads(raw_input)
            path = data.get("path") or data.get("file") or data.get("filename") or ""
            content = data.get("content") or data.get("text") or data.get("body") or ""
            if path:
                return str(path).strip(), str(content)
        except Exception:
            pass

    # 2. Multi-line format: first line is path, remaining lines are content
    if "\n" in raw_input:
        lines = raw_input.split("\n", 1)
        first_line = lines[0].strip()
        if first_line.lower().startswith("path:"):
            first_line = first_line[5:].strip()
        elif first_line.lower().startswith("filename:"):
            first_line = first_line[9:].strip()
        path = first_line.strip("'\"")
        content = lines[1]
        if content.lower().startswith("content:"):
            content = content[8:].lstrip()
        return path, content

    # 3. Key-value format: path="xyz", content="abc"
    kv_match = re.match(
        r'''(?:path|filename|file)\s*=\s*['"]([^'"]+)['"]\s*,?\s*(?:content|text)\s*=\s*['"](.*)['"]''',
        raw_input,
        re.DOTALL | re.IGNORECASE
    )
    if kv_match:
        return kv_match.group(1).strip(), kv_match.group(2).strip()

    kv_match = re.match(
        r'''(?:path|filename|file)\s*:\s*(\S+)\s*,?\s*(?:content|text)\s*:\s*(.*)''',
        raw_input,
        re.DOTALL | re.IGNORECASE
    )
    if kv_match:
        return kv_match.group(1).strip(), kv_match.group(2).strip().strip("'\"")

    # 4. Comma separated in single line: "path, content"
    if "," in raw_input:
        parts = raw_input.split(",", 1)
        p = parts[0].strip().strip("'\"")
        c = parts[1].strip().strip("'\"")
        # Strip leading key names if present (filename=, path=, file=)
        p = re.sub(r'^(?:filename|path|file)\s*=\s*', '', p, flags=re.IGNORECASE).strip("'\"")
        c = re.sub(r'^content\s*=\s*', '', c, flags=re.IGNORECASE).strip("'\"")
        return p, c

    # Fallback: path only
    return raw_input.strip().strip("'\""), ""


TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
    "web_search": web_search,
}


def load_tools_config(path: str = "tools.json") -> Dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {
            "list_files": {"enabled": True},
            "read_file": {"enabled": True},
            "write_file": {"enabled": True},
            "run_command": {"enabled": True, "timeout": 30},
            "web_search": {"enabled": True, "timeout": 20, "max_results": 4},
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def execute_tool(action: str, raw_input: str, tools_config: Dict[str, Any]) -> str:
    action = action.strip()
    tool_cfg = tools_config.get(action)

    if not tool_cfg or not tool_cfg.get("enabled", True):
        return f"ERROR: Tool '{action}' does not exist or is disabled."

    if action not in TOOL_FUNCTIONS:
        return f"ERROR: Tool '{action}' is not implemented."

    clean_input = (raw_input or "").strip()

    if action == "list_files":
        return list_files(clean_input or ".")

    elif action == "read_file":
        return read_file(clean_input)

    elif action == "write_file":
        path, content = parse_write_file_args(clean_input)
        if not path:
            return "ERROR: write_file requires a path argument."
        return write_file(path, content)

    elif action == "run_command":
        timeout = tool_cfg.get("timeout", 30)
        return run_command(clean_input, timeout=timeout)

    elif action == "web_search":
        timeout = tool_cfg.get("timeout", 20)
        max_results = tool_cfg.get("max_results", 4)
        return web_search(clean_input, timeout=timeout, max_results=max_results)

    return f"ERROR: Tool '{action}' execution handler not found."
