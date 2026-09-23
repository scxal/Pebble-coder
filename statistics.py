#!/usr/bin/env python3
"""Estadisticas del REPL: barra inferior SIEMPRE visible y tiempo del LLM.

Modulo stdlib-only, sin dependencias de agent.py ni menu.py (sin ciclos).
La salida es neutra en idioma (etiquetas tipo `GPU`, `ctx`, `t/s`), por lo
que no hay claves i18n aqui.

La barra queda FIJA en la ultima fila de la terminal: al activarla se
reserva esa fila con una region de scroll (DECSTBM, `\\033[1;{rows-1}r`), de
modo que todo lo que se imprima (pensamiento, stream del modelo, salida de
herramientas) scrollea por encima y la barra nunca desaparece. Las
reescrituras usan `\\0337`/`\\0338` (DECSC/DECRC) para no mover el cursor de
quien esta imprimiendo.

- `idle_tick()`: hook del REPL (tras tecla y en reposo) — activa, refresca
  o apaga la barra segun la config.
- `tick_live()`: refresco rapido (0.15s) durante una peticion al LLM: el
  segmento `LLM` cuenta los segundos en vivo hasta terminar la respuesta.
- `begin/end_answer`, `begin/end_request`, `note_*`: fronteras de timing
  y uso de tokens que engancha agent.py.

Sin psutil: CPU de /proc/stat (dos muestras), RAM de /proc/meminfo, GPU de
/sys/class/drm (amdgpu) con fallback nvidia-smi y radeontop (ultimo recurso).
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import select
    import termios
    import tty
    _HAS_TERM = True
except ImportError:  # sin termios (p. ej. Windows) no hay consulta de cursor
    _HAS_TERM = False

_GPU_GLOB = "/sys/class/drm/card*/device/gpu_busy_percent"
_LIVE_TICK = 0.15
_GPU_CACHE_S = 1.0
_TOOL_MIN_S = 2.0
_TOOL_BACKOFF_S = 60.0

_config: Optional[Dict[str, object]] = None

_answer_t0: Optional[float] = None
_last_answer_s: Optional[float] = None

_req_t0: Optional[float] = None
_live_last_write = 0.0
_usage_completion: Optional[int] = None
_last_completion_tokens: Optional[int] = None
_last_req_s: Optional[float] = None
_last_tps: Optional[float] = None

_ctx_est: Optional[int] = None
_ctx_from_usage: Optional[int] = None

_active = False
_bar_rows = 0
_bar_cols = 0
_last_bar: Optional[str] = None

_cpu_prev: Optional[Tuple[int, int]] = None
_gpu_path: Optional[str] = None
_gpu_path_checked = -1e9
_gpu_cache: Optional[str] = None
_gpu_cache_t = -1e9
_nvidia_bin: object = "unknown"  # None = ausente, str = path
_tool_t = -1e9
_tool_backoff_t = -1e9


def bind(config: Optional[Dict[str, object]]) -> None:
    """Fija el dict de config vivo (misma referencia que usa el REPL)."""
    global _config
    _config = config


def reset() -> None:
    """Limpia todo el estado (para tests). No escribe en la terminal."""
    global _config, _answer_t0, _last_answer_s, _req_t0
    global _live_last_write, _usage_completion
    global _last_completion_tokens, _last_req_s, _last_tps
    global _ctx_est, _ctx_from_usage, _active, _bar_rows, _bar_cols
    global _last_bar, _cpu_prev, _gpu_path, _gpu_path_checked
    global _gpu_cache, _gpu_cache_t, _nvidia_bin, _tool_t, _tool_backoff_t
    _config = None
    _answer_t0 = None
    _last_answer_s = None
    _req_t0 = None
    _live_last_write = 0.0
    _usage_completion = None
    _last_completion_tokens = None
    _last_req_s = None
    _last_tps = None
    _ctx_est = None
    _ctx_from_usage = None
    _active = False
    _bar_rows = 0
    _bar_cols = 0
    _last_bar = None
    _cpu_prev = None
    _gpu_path = None
    _gpu_path_checked = -1e9
    _gpu_cache = None
    _gpu_cache_t = -1e9
    _nvidia_bin = "unknown"
    _tool_t = -1e9
    _tool_backoff_t = -1e9


def enabled() -> bool:
    """`stats` en config: on por defecto (acepta bool o string on/off)."""
    val = True if _config is None else _config.get("stats", True)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("on", "true", "yes", "1", "enabled")
    return bool(val)


def is_active() -> bool:
    return _active


# --- Fronteras de tiempo -------------------------------------------------


def begin_answer() -> None:
    global _answer_t0
    _answer_t0 = time.monotonic()


def end_answer() -> None:
    global _answer_t0, _last_answer_s
    if _answer_t0 is not None:
        _last_answer_s = time.monotonic() - _answer_t0
        _answer_t0 = None


def begin_request() -> None:
    global _req_t0, _usage_completion
    _req_t0 = time.monotonic()
    _usage_completion = None


def end_request(completion_text: Optional[str] = None) -> None:
    """Cierra la peticion HTTP actual y calcula duracion + t/s."""
    global _req_t0, _last_req_s, _last_tps, _last_completion_tokens
    global _usage_completion
    if _req_t0 is None:
        return
    elapsed = max(time.monotonic() - _req_t0, 1e-6)
    _req_t0 = None
    _last_req_s = elapsed
    _last_completion_tokens = _usage_completion
    tokens = _usage_completion
    if tokens is None and completion_text:
        tokens = max(1, len(completion_text) // 4)
    if tokens:
        _last_tps = tokens / elapsed
    _usage_completion = None


def note_usage(usage: object) -> None:
    """`usage` del servidor (OpenAI-compatible): tokens exactos."""
    global _usage_completion, _ctx_from_usage
    if not isinstance(usage, dict):
        return
    pt = usage.get("prompt_tokens")
    if isinstance(pt, int) and pt > 0:
        _ctx_from_usage = pt
    ct = usage.get("completion_tokens")
    if isinstance(ct, int) and ct > 0:
        _usage_completion = ct


def note_context(messages: List[Dict[str, str]]) -> None:
    """Estima el contexto saliente (chars/4); invalida el valor exacto."""
    global _ctx_est, _ctx_from_usage
    try:
        total = sum(len(str(m.get("content", ""))) for m in messages)
    except (AttributeError, TypeError):
        total = 0
    _ctx_est = total // 4
    _ctx_from_usage = None


def last_answer_s() -> Optional[float]:
    if _answer_t0 is not None:
        return time.monotonic() - _answer_t0
    return _last_answer_s


def last_req_s() -> Optional[float]:
    if _req_t0 is not None:
        return time.monotonic() - _req_t0
    return _last_req_s


def last_tps() -> Optional[float]:
    return _last_tps


def last_completion_tokens() -> Optional[int]:
    return _last_completion_tokens


def last_ctx() -> Optional[int]:
    return _ctx_from_usage if _ctx_from_usage is not None else _ctx_est


# --- Colores y medida ------------------------------------------------------


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def dim(text: str) -> str:
    return _c(text, "90")


def _terminal_size() -> Tuple[int, int]:
    try:
        sz = os.get_terminal_size()
        if sz.lines > 0 and sz.columns > 0:
            return sz.lines, sz.columns
    except (OSError, ValueError):
        pass
    return 24, 80


def _clip(text: str, width: int) -> str:
    """Recorta para que la fila no haga wrap (romperia el anclaje)."""
    limit = max(1, width - 1)
    return text[:limit] if len(text) > limit else text


# --- Barra global anclada a la ultima fila --------------------------------


def _set_region(rows: int) -> None:
    """Reserva la ultima fila: el scroll ocurre solo en 1..rows-1."""
    sys.stdout.write(f"\0337\033[1;{rows - 1}r\0338")
    sys.stdout.flush()


def _write_bar_abs(text: str, rows: int) -> None:
    """Reescribe la barra en la ultima fila sin alterar el cursor actual."""
    sys.stdout.write(f"\0337\033[{rows};1H\033[K{text}\0338")
    sys.stdout.flush()


def _cursor_row() -> Optional[int]:
    """Fila actual del cursor via `\\033[6n` (solo al activar)."""
    if not _HAS_TERM or not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033[6n")
        sys.stdout.flush()
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            return None
        data = os.read(fd, 64)
    except (OSError, ValueError):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    m = re.search(rb"\x1b\[(\d+);(\d+)R", data)
    return int(m.group(1)) if m else None


def status_row() -> Optional[str]:
    """Texto (dim, truncado al ancho) de la barra, o None si esta apagada."""
    if not enabled() or not sys.stdout.isatty():
        return None
    return dim(_clip(_bar_text(), _terminal_size()[1]))


def activate_bar() -> None:
    """Fija la barra en la ultima fila. Idempotente; no-op sin TTY/stats off."""
    global _active, _bar_rows, _bar_cols, _last_bar
    if not enabled() or not sys.stdout.isatty():
        return
    rows, cols = _terminal_size()
    if rows < 3:
        return
    if not _active:
        _set_region(rows)
        _active = True
        # Si el cursor quedo EN la fila reservada (pantalla llena), sube una:
        # a partir de ahi solo puede scrollear dentro de la region.
        row = _cursor_row()
        if row is not None and row > rows - 1:
            sys.stdout.write("\033[1A")
            sys.stdout.flush()
    _bar_rows, _bar_cols = rows, cols
    text = status_row()
    if text is None:
        return
    _write_bar_abs(text, rows)
    _last_bar = text


def deactivate_bar() -> None:
    """Limpia la barra y restaura el scroll normal de la terminal."""
    global _active, _bar_rows, _bar_cols, _last_bar
    if not _active:
        return
    rows, _ = _terminal_size()
    sys.stdout.write(f"\0337\033[{rows};1H\033[K\0338\033[r")
    sys.stdout.flush()
    _active = False
    _bar_rows = 0
    _bar_cols = 0
    _last_bar = None


def redraw_bar() -> None:
    """Reescribe la barra si cambio (o si hubo resize de terminal)."""
    global _bar_rows, _bar_cols, _last_bar
    if not _active or not enabled() or not sys.stdout.isatty():
        return
    rows, cols = _terminal_size()
    if (rows, cols) != (_bar_rows, _bar_cols):
        if rows < 3:
            deactivate_bar()
            return
        _set_region(rows)  # reaplica la region tras un resize
        _bar_rows, _bar_cols = rows, cols
        _last_bar = None
    text = status_row()
    if text is None or text == _last_bar:
        return
    _write_bar_abs(text, rows)
    _last_bar = text


def idle_tick() -> None:
    """Hook del REPL (tras cada tecla y en reposo): sincroniza la barra."""
    if not enabled():
        deactivate_bar()
        return
    if not _active:
        activate_bar()
    else:
        redraw_bar()


def tick_live() -> None:
    """Refresco rapido de la barra durante una peticion (crono en vivo)."""
    global _live_last_write
    if not _active or not enabled():
        return
    now = time.monotonic()
    if now - _live_last_write < _LIVE_TICK:
        return
    _live_last_write = now
    redraw_bar()


# --- Muestreadores del sistema --------------------------------------------


def parse_proc_stat(line: str) -> Tuple[int, int]:
    """Primera linea de /proc/stat -> (idle, total) en ticks."""
    vals = [int(x) for x in line.split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return idle, sum(vals)


def _cpu_percent(prev: Tuple[int, int], cur: Tuple[int, int]) -> Optional[float]:
    didle = cur[0] - prev[0]
    dtotal = cur[1] - prev[1]
    if dtotal <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (1.0 - didle / dtotal)))


def _sample_cpu() -> str:
    global _cpu_prev
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            cur = parse_proc_stat(f.readline())
    except (OSError, ValueError, IndexError):
        return "-"
    prev, _cpu_prev = _cpu_prev, cur
    if prev is None:
        return "-"
    pct = _cpu_percent(prev, cur)
    return "-" if pct is None else f"{pct:.0f}%"


def parse_proc_meminfo(text: str) -> Tuple[int, int]:
    """-> (MemTotal kB, MemAvailable kB); fallback a Free+Buffers+Cached."""
    total = avail = None
    free = buffers = cached = 0
    for line in text.splitlines():
        try:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
            elif line.startswith("MemFree:"):
                free = int(line.split()[1])
            elif line.startswith("Buffers:"):
                buffers = int(line.split()[1])
            elif line.startswith("Cached:"):
                cached = int(line.split()[1])
        except (IndexError, ValueError):
            continue
    if total is None:
        raise ValueError("MemTotal missing")
    if avail is None:
        avail = free + buffers + cached
    return total, avail


def _sample_ram() -> str:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            total, avail = parse_proc_meminfo(f.read())
    except (OSError, ValueError):
        return "-"
    used = (total - avail) / 1048576.0  # kB -> GiB
    return f"{used:.1f}G/{total / 1048576.0:.0f}G"


def _find_gpu_path(pattern: str = _GPU_GLOB) -> Optional[str]:
    try:
        matches = sorted(glob.glob(pattern))
    except (OSError, ValueError):
        return None
    return matches[0] if matches else None


def read_gpu_busy(path: str) -> Optional[int]:
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _sample_gpu_tool() -> str:
    """Fallbacks: nvidia-smi (>=2s), radeontop (ultimo recurso, 60s)."""
    global _nvidia_bin, _tool_t, _tool_backoff_t
    now = time.monotonic()
    if now < _tool_backoff_t or now - _tool_t < _TOOL_MIN_S:
        return "-"
    _tool_t = now

    if _nvidia_bin == "unknown":
        _nvidia_bin = shutil.which("nvidia-smi") or None
    if _nvidia_bin:
        try:
            out = subprocess.run(
                [_nvidia_bin, "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1.5,
            )
            m = re.search(r"\d+", out.stdout)
            if m:
                return f"{m.group()}%"
        except (OSError, subprocess.SubprocessError):
            _nvidia_bin = None

    rt = shutil.which("radeontop")
    if rt:
        try:
            out = subprocess.run([rt, "-t", "1", "-"],
                                 capture_output=True, text=True, timeout=2)
            m = (re.search(r"gpu[^0-9%]{0,24}(\d+(?:\.\d+)?)", out.stdout, re.I)
                 or re.search(r"(\d+(?:\.\d+)?)\s*%", out.stdout))
            if m:
                return f"{float(m.group(1)):.0f}%"
        except (OSError, subprocess.SubprocessError):
            pass
        _tool_backoff_t = now + _TOOL_BACKOFF_S
    else:
        _tool_backoff_t = now + _TOOL_BACKOFF_S
    return "-"


def _sample_gpu() -> str:
    global _gpu_path, _gpu_path_checked, _gpu_cache, _gpu_cache_t
    now = time.monotonic()
    if _gpu_cache is not None and now - _gpu_cache_t < _GPU_CACHE_S:
        return _gpu_cache
    if now - _gpu_path_checked >= _TOOL_BACKOFF_S:
        _gpu_path_checked = now
        if _gpu_path is None or read_gpu_busy(_gpu_path) is None:
            _gpu_path = _find_gpu_path()
    if _gpu_path:
        v = read_gpu_busy(_gpu_path)
        out = f"{v}%" if v is not None else _sample_gpu_tool()
    else:
        out = _sample_gpu_tool()
    _gpu_cache = out
    _gpu_cache_t = now
    return out


# --- Render de la barra ---------------------------------------------------


def _fmt_tps(tps: float) -> str:
    return f"{tps:.0f} t/s" if tps >= 10 else f"{tps:.1f} t/s"


def _fmt_k(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _fmt_secs(s: float) -> str:
    return f"{s:.2f}s" if s < 10 else f"{s:.1f}s"


def _bar_text() -> str:
    t_ans = last_answer_s()
    seg_llm = f"LLM {_fmt_secs(t_ans)}" if t_ans is not None else "LLM -"
    seg_tps = f"{_fmt_tps(_last_tps)}" if _last_tps else "t/s -"
    ctx = last_ctx()
    window = 32768
    if isinstance(_config, dict):
        try:
            window = int(_config.get("context_window", 32768))
        except (TypeError, ValueError):
            window = 32768
    win_txt = f"{window // 1000}k" if window >= 1000 else str(window)
    seg_ctx = f"ctx {_fmt_k(ctx)}/{win_txt}" if ctx is not None else "ctx -"
    return (" · ".join([seg_llm, seg_tps, seg_ctx,
                        f"GPU {_sample_gpu()}",
                        f"CPU {_sample_cpu()}",
                        f"RAM {_sample_ram()}"]))
