import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


# --- Translation loading ---
_SCRIPT_DIR = Path(__file__).resolve().parent
_lang = "es"
try:
    _cfg = json.loads((_SCRIPT_DIR / "config.json").read_text())
    _lang = (_cfg.get("language") or "es") if _cfg.get("language") in ("es", "en") else "es"
except Exception:
    pass

_t_es = {}
try:
    _t_es = json.loads((_SCRIPT_DIR / "translations_es.json").read_text())
except FileNotFoundError:
    pass

_translations = {}
try:
    _translations = json.loads((_SCRIPT_DIR / f"translations_{_lang}.json").read_text())
except FileNotFoundError:
    _translations = {}

_tool_t = _translations.get("tools", {})


def t(key: str, **kwargs) -> str:
    val = _tool_t.get(key, _t_es.get("tools", {}).get(key, ""))
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return val


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
        return t("path_not_exists").format(path=cleaned_path)
    if not target.is_dir():
        return t("path_not_directory").format(path=cleaned_path)

    try:
        entries = sorted(list(target.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        if not entries:
            return t("directory_empty")

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
        return t("permission_denied_list").format(path=cleaned_path)
    except Exception as exc:
        return t("listing_failed").format(path=cleaned_path, exc=exc)


def read_file(path: str) -> str:
    cleaned_path = path.strip().strip("'\"")
    if not cleaned_path:
        return t("file_path_empty")

    target = Path(cleaned_path).resolve()
    if not target.exists():
        return t("file_not_found").format(path=cleaned_path)
    if target.is_dir():
        return t("is_directory").format(path=cleaned_path)

    try:
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            content = target.read_text(encoding="latin-1", errors="replace")

        lines = content.splitlines()
        if len(lines) > MAX_READ_LINES:
            truncated = "\n".join(lines[:MAX_READ_LINES])
            return f"{truncated}{t('truncated_lines').format(lines=MAX_READ_LINES)}"

        if len(content) > MAX_OUTPUT_CHARS:
            return content[:MAX_OUTPUT_CHARS] + t('truncated_chars').format(chars=MAX_OUTPUT_CHARS)

        return content if content else t("empty_file")
    except PermissionError:
        return t("permission_denied_read").format(path=cleaned_path)
    except Exception as exc:
        return t("read_failed").format(path=cleaned_path, exc=exc)


def write_file(path: str, content: str) -> str:
    cleaned_path = path.strip().strip("'\"")
    if not cleaned_path:
        return t("write_path_empty")

    try:
        target = Path(cleaned_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return t("write_success").format(path=cleaned_path, count=len(content))
    except PermissionError:
        return t("permission_denied_write").format(path=cleaned_path)
    except Exception as exc:
        return t("write_failed").format(path=cleaned_path, exc=exc)


def run_command(command: str, timeout: int = 30) -> str:
    command = command.strip()
    if not command:
        return t("command_empty")

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
            result = result[:MAX_OUTPUT_CHARS] + t('truncated_chars').format(chars=MAX_OUTPUT_CHARS)

        return result
    except subprocess.TimeoutExpired:
        return t("command_timeout").format(seconds=timeout)
    except Exception as exc:
        return t("command_failed").format(exc=exc)


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


# Palabras vacias para no usarlas como terminos de relevancia al destilar.
_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "que", "con",
    "por", "para", "es", "del", "se", "lo", "como", "mas", "más", "su", "al",
    "no", "o", "pero", "este", "esta", "esto", "qué", "cuál", "cuando", "donde",
    "quien", "quién", "sobre", "info", "informacion", "información", "resultado",
    "the", "a", "an", "and", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "what", "how", "why", "when", "where", "who", "can", "do",
    "does", "it", "its", "at", "by", "as", "or", "not", "but", "this", "that",
    "these", "those", "about", "i", "you", "me", "my", "tell", "need", "want",
    "know", "search", "give", "please",
}

# JS que extrae resultados estructurados de Bing (titulo, URL limpia, snippet).
_EXTRACT_JS = r"""(function(){
  // Bing envuelve cada resultado en un redirect /ck/a?...&u=a1<base64>. Aqui se
  // resuelve la URL real (base64 en el parametro 'u=a1').
  function cleanUrl(h){
    if(!/^https?:/i.test(h)) return '';
    var u;
    try{ u = new URL(h); }catch(e){ return ''; }
    if(/bing\.com$|microsoft/i.test(u.hostname)){
      var m = h.match(/[?&]u=a1([A-Za-z0-9_\-]+)/);
      if(!m) return '';
      var b64 = m[1].replace(/-/g,'+').replace(/_/g,'/');
      while(b64.length % 4) b64 += '=';
      try{
        var raw = atob(b64);
        var bytes = new Uint8Array(raw.length);
        for(var j=0;j<raw.length;j++) bytes[j] = raw.charCodeAt(j)&0xff;
        var dec = new TextDecoder().decode(bytes);
        return /^https?:/i.test(dec) ? dec : '';
      }catch(e){ return ''; }
    }
    return u.href;
  }
  function textOf(el){ return el ? (el.textContent||'').trim() : ''; }
  var items = document.querySelectorAll('#b_results > li.b_algo');
  if(!items.length){ items = document.querySelectorAll('li'); }
  var all = Array.prototype.slice.call(items, 0, 60);
  var seen = {}, out = [];
  for(var i=0;i<all.length && out.length<10;i++){
    var li = all[i];
    var a = li.querySelector('h2 a') || li.querySelector('h3 a') || li.querySelector('a');
    var url = a ? cleanUrl(a.href) : '';
    if(!url || seen[url]) continue; seen[url] = 1;
    var title = textOf(a);
    if(title.length < 3) continue;
    var snip = textOf(li.querySelector('.b_caption p') || li.querySelector('.b_lineclamp2, .b_lineclamp3, .b_lineclamp4') || li);
    out.push({t:title, u:url, s:snip.slice(0,280)});
  }
  return JSON.stringify(out);
})()"""


def _query_keywords(query: str) -> list:
    """Extrae los terminos significativos de la consulta para filtrar relevancia."""
    words = re.findall(r"[a-záéíóúñü0-9]+", query.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS][:8]


def _extract_results(bin_path: str, query: str, timeout: int) -> list:
    """Abre Bing y devuelve resultados estructurados como lista de dicts {t,u,s}."""
    search_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    if not _run_browser(bin_path, ["open", search_url, "--timeout", str(timeout * 1000)], timeout + 5):
        return []
    # Reintenta la extraccion: la pagina puede no haber terminado de renderizar.
    for _ in range(3):
        out = _run_browser(bin_path, ["eval", _EXTRACT_JS], timeout)
        try:
            data = json.loads(out)
            if isinstance(data, str):
                data = json.loads(data)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, list) and data:
            break
        time.sleep(1)

    if not isinstance(data, list):
        return []
    results = []
    for r in data:
        url = (r.get("u") or "").strip()
        title = (r.get("t") or "").strip()
        snippet = (r.get("s") or "").strip()
        if url and title:
            results.append({"u": url, "t": title, "s": snippet})
    return results


def _relevance_filter(text: str, keywords: list, budget: int) -> str:
    """Conserva solo las lineas relacionadas con los terminos de la consulta."""
    if not keywords:
        return text[:budget]
    lines = text.splitlines()
    kept = [False] * len(lines)
    for i, ln in enumerate(lines):
        low = ln.lower()
        if any(k in low for k in keywords):
            for j in range(max(0, i - 1), min(len(lines), i + 2)):
                kept[j] = True
    filtered = "\n".join(ln for ln, keep in zip(lines, kept) if keep).strip()
    if not filtered:
        filtered = text
    return filtered[:budget]


def _distill_page(bin_path: str, url: str, keywords: list, timeout: int, budget: int) -> str:
    """Abre una pagina en el navegador y destila el texto relevante renderizado."""
    if not _run_browser(bin_path, ["open", url, "--timeout", str(timeout * 1000)], timeout + 5):
        return ""
    out = _browser_get_text(bin_path, "main", timeout) or _browser_get_text(bin_path, "body", timeout)
    if not out or "no matching page sections" in out.lower():
        return ""
    return _relevance_filter(out, keywords, budget)


def web_search(query: str, timeout: int = 20, max_results: int = 4, auto_fetch: str = "first") -> str:
    query = query.strip().strip("'\"")
    if not query:
        return t("search_query_empty")

    bin_path = find_agent_browser()
    if not bin_path:
        return t("browser_not_installed")

    keywords = _query_keywords(query)
    fetch_budget = min(2400, MAX_OUTPUT_CHARS)

    # URL directa -> destilar el contenido de la pagina entregada.
    if query.startswith("http://") or query.startswith("https://"):
        distilled = _distill_page(bin_path, query, keywords, timeout, fetch_budget)
        if distilled:
            return t("page_distilled_header").format(url=query, text=distilled)
        if _run_browser(bin_path, ["open", query, "--timeout", str(timeout * 1000)], timeout + 5):
            text = _browser_get_text(bin_path, "main", timeout)
            return text[:2500] if text else t("page_content_empty")
        return t("open_url_failed")

    results = _extract_results(bin_path, query, timeout)
    if not results:
        search_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
        if _run_browser(bin_path, ["open", search_url, "--timeout", str(timeout * 1000)], timeout + 5):
            text = _browser_get_text(bin_path, "main", timeout)
            if text:
                if len(text) > MAX_OUTPUT_CHARS:
                    text = text[:MAX_OUTPUT_CHARS] + t('truncated_chars').format(chars=MAX_OUTPUT_CHARS)
                return t("search_result_header").format(query=query, text=text)
        return t("no_search_results").format(query=query)

    results = results[:max(1, min(int(max_results or 4), len(results)))]

    parts = [t("search_header").format(query=query)]
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. {r['t']}\n   URL: {r['u']}\n   {r['s']}")

    auto_fetch = (auto_fetch or "none").strip().lower()
    if auto_fetch in ("first", "top", "top2", "2", "true", "yes"):
        fetch_count = 1 if auto_fetch in ("first", "true", "yes") else min(2, len(results))
        used = sum(len(p) for p in parts)
        per_page = max(200, (fetch_budget - used - 200) // fetch_count)
        for i, r in enumerate(results[:fetch_count], 1):
            content = _distill_page(bin_path, r["u"], keywords, timeout, per_page)
            if content:
                parts.append(f"[Content from result {i} ({r['t']})]: {content}")

    text = "\n\n".join(parts)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + t('truncated_chars').format(chars=MAX_OUTPUT_CHARS)
    return text


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
            "web_search": {"enabled": True, "timeout": 20, "max_results": 4, "auto_fetch": "first"},
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
            return t("write_path_empty")
        return write_file(path, content)

    elif action == "run_command":
        timeout = tool_cfg.get("timeout", 30)
        return run_command(clean_input, timeout=timeout)

    elif action == "web_search":
        timeout = tool_cfg.get("timeout", 20)
        max_results = tool_cfg.get("max_results", 4)
        auto_fetch = tool_cfg.get("auto_fetch", "first")
        return web_search(clean_input, timeout=timeout, max_results=max_results, auto_fetch=auto_fetch)

    return f"ERROR: Tool '{action}' execution handler not found."
