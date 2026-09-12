# Agente ReAct Ligero para Modelos Locales

Agente ReAct minimalista en Python diseñado para operar con baja latencia y bajo consumo de memoria en hardware doméstico (por ejemplo, GPUs de 8GB como RX 6600 o RTX 3060). Funciona con modelos locales pequeños y ultra-rápidos (4B-8B parámetros) como **Gemma 4 E4B**, **Qwen 2.5 / 3-Coder 7B/8B**, **Phi 4 Mini** a través de servidores compatibles con la API de OpenAI (Ollama, LM Studio, vLLM o Groq).

---

## Índice

1. [Características Principales](#características-principales)
2. [Estructura del Proyecto](#estructura-del-proyecto)
3. [Requisitos Previos](#requisitos-previos)
4. [Guía de Inicio Rápido](#guía-de-inicio-rápido)
5. [Instrucciones de Configuración en Archivos de Texto](#instrucciones-de-configuración-en-archivos-de-texto)
   - [Configuración General (config.json)](#1-configuración-general-configjson)
   - [Control de Visibilidad y Modo Chat Limpio (debug, thought, observation)](#control-de-visibilidad-y-modo-chat-limpio)
   - [Configuración de Herramientas (tools.json)](#2-configuración-de-herramientas-toolsjson)
   - [Personalización del Prompt (system_prompt.md)](#3-personalización-del-prompt-system_promptmd)
   - [Uso del Formato XML Opcional](#4-uso-del-formato-xml-opcional)
6. [Modos de Uso](#modos-de-uso)
   - [Modo Consola Interactiva (REPL)](#1-modo-consola-interactiva)
   - [Modo Comando Directo (CLI)](#2-modo-comando-directo)
7. [Herramientas Disponibles (incluyendo web_search con agent-browser)](#herramientas-disponibles)
8. [Resolución de Problemas (Troubleshooting)](#resolución-de-problemas-troubleshooting)

---

## Características Principales

- **Chat limpio por defecto:** Solo muestra las interacciones y respuestas del asistente. El razonamiento interno (`Thought`) y el volcado de lecturas de archivos u observaciones no saturan la pantalla a menos que se activen.
- **Búsqueda web ordenada (`web_search`):** Integración nativa con `agent-browser` para realizar búsquedas web concisas y lectura de páginas sin sobrecargar el contexto del modelo ni requerir APIs de pago.
- **Sin frameworks pesados:** No utiliza LangChain, CrewAI, AutoGen ni librerías con dependencias complejas.
- **Sin Function Calling complejo:** Utiliza el patrón ReAct clásico basado en texto estructurado (`Thought / Action / Input / Observation / Final Answer`), ideal para modelos pequeños que alucinan o fallan con JSON tool calling.
- **100% Configurable sin tocar código:** Los modelos, endpoints, herramientas, visibilidad de logs y prompts residen en archivos de texto editables (`.json` y `.md`).

---

## Estructura del Proyecto

```text
react-agent/
│
├── agent.py            # Loop principal ReAct y consola interactiva
├── parser.py           # Parser por expresiones regulares (texto plano y XML)
├── tools.py            # Implementación de herramientas (incluye web_search con agent-browser)
├── config.json         # Configuración general (modelo, endpoint, flags de visibilidad, etc.)
├── tools.json          # Control de activación y parámetros de las herramientas
├── system_prompt.md    # Prompt del sistema estándar ReAct (editable)
├── system_prompt_xml.md# Prompt del sistema alternativo en formato XML
├── requirements.txt    # Dependencias de Python (solo 'requests')
├── lineamientos.md     # Especificaciones técnicas del proyecto
└── README.md           # Esta guía de instrucciones
```

---

## Requisitos Previos

1. **Python 3.10 o superior**.
2. **Servidor local de IA:**
   - [Ollama](https://ollama.com/) (recomendado para Linux/macOS/Windows).
   - O [LM Studio](https://lmstudio.ai/), [vLLM](https://github.com/vllm-project/vllm), [LocalAI](https://localai.io/), o cualquier servidor con endpoint compatible con OpenAI (`/v1/chat/completions`).
3. **agent-browser:** Herramienta de navegación y lectura instalada en el sistema.

---

## Guía de Inicio Rápido

### Paso 1: Instalar dependencias

```bash
pip install -r requirements.txt
```

---

### Paso 2: Iniciar tu servidor local y descargar un modelo

Si utilizas **Ollama**, descarga y ejecuta el modelo deseado:

```bash
# Iniciar el servicio (si no corre como servicio del sistema)
ollama serve

# En otra terminal, descargar el modelo:
ollama pull gemma4:e4b
# o bien:
ollama pull qwen2.5-coder:7b
```

---

### Paso 3: Iniciar el agente en la consola

```bash
python3 agent.py
```

Aparecerá el banner de bienvenida con el estado de configuración:

```text
============================================================
  Agente ReAct Ligero para Modelos Locales
============================================================
Modelo      : gemma4:e4b
Endpoint    : http://localhost:11434/v1
Formato     : text
Debug       : off
Thought     : off
Observation : off
Tools       : list_files, read_file, write_file, run_command, web_search
Escribe 'exit' o 'quit' para salir.
------------------------------------------------------------

Tú > 
```

---

## Instrucciones de Configuración en Archivos de Texto

No necesitas recompilar ni tocar ningún archivo `.py` para cambiar el comportamiento del agente.

### 1. Configuración General (`config.json`)

Edita `config.json` con cualquier editor de texto:

```json
{
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

#### Opciones disponibles:

| Clave | Tipo | Valores | Descripción |
|---|---|---|---|
| `model` | string | `"gemma4:e4b"`, etc. | Nombre del modelo en tu servidor local |
| `base_url` | string | URL | URL base de la API compatible con OpenAI |
| `api_key` | string | `"ollama"`, etc. | Clave de API si tu servidor la requiere |
| `temperature` | float | `0.1` - `0.3` | Aleatoriedad en la generación (valores bajos dan mayor precisión en ReAct) |
| `max_iterations` | int | `10` | Límite máximo de ciclos por consulta |
| `timeout` | int | `30` | Tiempo máximo de espera en segundos por respuesta del LLM |
| `format` | string | `"text"` o `"xml"` | Formato de pensamiento y acción |
| `debug` | string/bool | `"on"` / `"off"` | Activa el modo verbose con todo el registro detallado |
| `thought` | string/bool | `"on"` / `"off"` | Muestra el pensamiento interno del modelo en pantalla |
| `observation` | string/bool | `"on"` / `"off"` | Muestra el contenido de observaciones (lectura de archivos, comandos) |
| `system_prompt_file` | string | ruta `.md` | Archivo del prompt del sistema |
| `tools_file` | string | ruta `.json` | Archivo de configuración de herramientas |

---

### Control de Visibilidad y Modo Chat Limpio

Para evitar que la pantalla se inunde con datos innecesarios:

- **Modo Chat Limpio (`"debug": "off"`, `"thought": "off"`, `"observation": "off"`):**
  Es el comportamiento predeterminado. La pantalla solo muestra tus mensajes y la respuesta final del asistente. Si el agente consulta un archivo de 500 líneas o realiza una búsqueda web, el contenido se envía internamente al LLM, pero no se imprime en la terminal; solo verás un aviso de progreso limpio como `[Leyendo archivo: config.json]` o `[Buscando en la web: ...]`.

- **Ver solo los pensamientos (`"thought": "on"`):**
  Muestra el bloque `[Pensamiento]` del modelo mientras razona, manteniendo las observaciones de archivos ocultas.

- **Ver observaciones de herramientas (`"observation": "on"`):**
  Muestra el contenido devuelto por la ejecución de herramientas (archivos leídos, salidas de comandos, resultados web).

- **Modo Depuración Total (`"debug": "on"`):**
  Muestra todas las iteraciones paso a paso (`--- [Iteracion X/Y] ---`), `[Thought]`, `[Action]`, `[Input]`, `[Observation]` completo y `[Final Answer]`.

---

### 2. Configuración de Herramientas (`tools.json`)

```json
{
  "list_files": {
    "enabled": true,
    "description": "list_files(path) - Lista archivos y directorios en el path especificado (por defecto '.')."
  },
  "read_file": {
    "enabled": true,
    "description": "read_file(path) - Lee el contenido de texto de un archivo."
  },
  "write_file": {
    "enabled": true,
    "description": "write_file(path, content) - Sobrescribe o crea un archivo con el contenido especificado."
  },
  "run_command": {
    "enabled": true,
    "description": "run_command(command) - Ejecuta comandos shell del sistema con captura de stdout y stderr.",
    "timeout": 30
  },
  "web_search": {
    "enabled": true,
    "description": "web_search(query) - Busca en la web, devuelve resultados estructurados y destila el contenido de las paginas mas relevantes.",
    "timeout": 20,
    "max_results": 4,
    "auto_fetch": "first"
  }
}
```

- **Para desactivar una herramienta:** Cambia `"enabled": false`. El modelo no podrá invocarla.
- **Para configurar búsquedas web:** Ajusta `"max_results"` (nº de resultados), `"timeout"` en segundos y `"auto_fetch"` dentro de `"web_search"`. `"auto_fetch"` admite `"none"` (solo snippets), `"first"` (destila la página del mejor resultado, por defecto) o `"top"` (destila las dos primeras).

---

### 3. Personalización del Prompt (`system_prompt.md`)

Puedes abrir `system_prompt.md` y adaptar las instrucciones, idioma o personalidad del agente sin reiniciar nada.

---

### 4. Uso del Formato XML Opcional

Si tu modelo rinde mejor con XML, en `config.json` cambia:
```json
{
  "format": "xml",
  "system_prompt_file": "system_prompt_xml.md"
}
```

---

## Modos de Uso

### 1. Modo Consola Interactiva

```bash
python3 agent.py
```

Ejemplos de interacción:

```text
Tú > ¿Cuáles son las últimas novedades de Python 3.12?
[Buscando en la web: Python 3.12 novedades]

Asistente:
Python 3.12 introduce mejoras significativas en rendimiento, mejores mensajes de error sintáctico, la integración del nuevo parser y optimizaciones en el intérprete...
```

Para salir escribe `exit`, `quit` o presiona `Ctrl + C`.

### 2. Modo Comando Directo

Para pipelines o scripts:

```bash
python3 agent.py "Lee config.json y dime qué modelo está seleccionado"
```

---

## Herramientas Disponibles

1. **`web_search(query)`** *(única herramienta de investigación)*:
   - Utiliza la herramienta del sistema `agent-browser` para realizar búsquedas web en tiempo real (Bing).
   - Extrae resultados de forma **estructurada** (Nº, Título, URL limpia y Snippet descriptivo), respetando `max_results`.
   - Por defecto (`"auto_fetch": "first"`) también **destila el contenido relevante** de la página del mejor resultado (`agent-browser read`), filtrando por los términos de la consulta, de modo que el modelo obtiene la respuesta en una sola llamada.
   - Si la consulta es una URL (empieza con `http://` o `https://`), extrae y destila directamente el contenido de la página.
   - Limita estrictamente la longitud para no sobrecargar el contexto de modelos pequeños (4B-8B).
   - **El modelo no necesita una herramienta `web_fetch` aparte:** una llamada a `web_search` cubre búsqueda y lectura.

2. **`list_files(path)`**:
   - Lista archivos y carpetas del directorio indicado ordenados por tamaño.

3. **`read_file(path)`**:
   - Lee archivos de texto en UTF-8 con truncado seguro si excede límites de contexto.

4. **`write_file(path, content)`**:
   - Crea o sobrescribe archivos creando automáticamente carpetas intermedias.

5. **`run_command(command)`**:
   - Ejecuta comandos del sistema con tiempo límite (`timeout`) y captura de `stdout`/`stderr`.

---

## Resolución de Problemas (Troubleshooting)

### Error: `No se pudo conectar con el endpoint LLM`
- Verifica que Ollama esté iniciado: `curl http://localhost:11434/api/tags`.
- Si usas otro puerto, configúralo en `"base_url"` dentro de `config.json`.

### Error: `'agent-browser' tool is not installed or not found in PATH`
- Asegúrate de que `agent-browser` esté accesible en tu `$PATH` o en `~/.local/share/pi-node/.../bin`.

### Deseo ver paso a paso lo que hace el modelo
- Activa `"debug": "on"` en `config.json` para ver el ciclo ReAct completo.
