# REQUERIMIENTO: AGENTE REACT LIGERO PARA MODELOS LOCALES

## Objetivo

Crear un agente ReAct minimalista en Python diseñado para funcionar eficientemente con modelos pequeños y rápidos ejecutados localmente mediante Ollama o servidores compatibles con la API OpenAI.

El diseño debe priorizar:

- Baja latencia.
- Simplicidad.
- Bajo consumo de contexto.
- Compatibilidad con modelos de 4B-8B parámetros.
- Mínima dependencia de tool calling JSON.
- Compatibilidad con Gemma 4 E4B, Qwen3-Coder 8B y modelos similares.
- Capacidad de cambiar modelo sin modificar código.

No utilizar frameworks pesados como:

- LangChain
- CrewAI
- AutoGen
- Semantic Kernel

El proyecto debe tener la menor cantidad posible de dependencias externas.

---

## Filosofía de Diseño

Este agente está pensado para hardware doméstico y modelos rápidos.

Debe priorizar:

- Respuestas rápidas.
- Iteraciones cortas.
- Contextos pequeños.
- Herramientas sencillas.
- Robustez.

No intentar replicar Claude Code, OpenCode o Cursor.

No utilizar:

- MCP
- Function Calling OpenAI
- Planificadores multinivel
- Herramientas dinámicas
- Memoria persistente compleja
- Agentes anidados
- Multiagente

La filosofía es:

"Menos herramientas, más velocidad."

---

## Arquitectura General

Patrón ReAct clásico:

Usuario
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

El modelo únicamente genera texto.

Nunca ejecuta herramientas.

El runtime interpreta y ejecuta las acciones.

---

## Configuración

Toda la configuración debe almacenarse en un archivo externo:

config.json

Ejemplo:

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

Debe ser posible cambiar:

- modelo
- endpoint
- temperatura
- límite de iteraciones

sin modificar código.

Ejemplos de modelos válidos:

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

## Prompt del Sistema

Crear:

system_prompt.md

Contenido:

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

## Herramientas Iniciales

Implementar únicamente:

### list_files

Firma:

```python
list_files(path)
```

Descripción:

Lista archivos y directorios.

---

### read_file

Firma:

```python
read_file(path)
```

Descripción:

Lee archivos de texto.

---

### write_file

Firma:

```python
write_file(path, content)
```

Descripción:

Sobrescribe o crea archivos.

---

### run_command

Firma:

```python
run_command(command)
```

Descripción:

Ejecuta comandos shell.

Debe incluir:

- timeout configurable
- captura de stdout
- captura de stderr

---

## Parser

Implementar parser para:

```text
Thought: necesito inspeccionar el proyecto

Action: list_files

Input: .
```

Extrayendo:

```python
action = "list_files"
input = "."
```

Utilizar expresiones regulares simples.

Evitar parsers complejos.

---

## Loop Principal

Estructura recomendada:

```python
for iteration in range(max_iterations):
```

Proceso:

1. Enviar historial al modelo.
2. Obtener respuesta.
3. Buscar Final Answer.
4. Si existe, terminar.
5. Parsear Action.
6. Ejecutar herramienta.
7. Generar Observation.
8. Continuar.

---

## Condiciones de Salida

Salir cuando ocurra alguna de estas condiciones:

### Caso 1

```text
Final Answer:
```

### Caso 2

```python
iteration >= max_iterations
```

### Caso 3

Parser inválido.

### Caso 4

Herramienta inexistente.

### Caso 5

Error crítico de ejecución.

---

## Manejo de Errores

Si una herramienta falla:

```text
Observation:
ERROR: <mensaje>
```

Permitir que el modelo se recupere.

No finalizar inmediatamente.

---

## Optimización para Gemma 4

Preferir formato:

```text
Thought:
Action:
Input:
Observation:
```

Evitar:

```json
{
  "tool_calls": [...]
}
```

Evitar:

```json
{
  "function_call": ...
}
```

Gemma suele rendir mejor con texto estructurado que con Function Calling.

---

## Formato XML Opcional

Debe existir una opción configurable:

```json
{
  "format": "xml"
}
```

Cuando se utilice XML, el modelo debe responder:

```xml
<thought>
Necesito inspeccionar el proyecto.
</thought>

<action>
list_files
</action>

<input>
.
</input>
```

El runtime deberá parsearlo.

---

## Límite de Herramientas

No implementar inicialmente más de:

- list_files
- read_file
- write_file
- run_command

La meta es mantener el contexto pequeño.

Herramientas adicionales deben agregarse manualmente.

---

## Dependencias Permitidas

Preferentemente:

```text
requests
openai
json
re
pathlib
subprocess
typing
```

Evitar dependencias innecesarias.

---

## Estructura del Proyecto

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

## Requisitos de Calidad

El código generado debe:

- Ser fácil de leer.
- Tener pocos archivos.
- Ser extensible.
- Tener comentarios mínimos.
- Poder ejecutarse inmediatamente después de instalar dependencias.

---

## Objetivo Final

Construir un agente ReAct extremadamente ligero y rápido para hardware doméstico.

Hardware objetivo:

- RX 6600 8GB
- 32GB RAM
- Ubuntu Linux

Modelos objetivo:

- Gemma 4 E4B
- Qwen3-Coder 8B
- Phi 4 Mini
- Otros modelos rápidos de 4B-8B
- Groq-Llama-8B

La prioridad absoluta es:

1. Velocidad.
2. Robustez.
3. Bajo consumo de tokens.
4. Simplicidad.

No perseguir capacidades agentic avanzadas a costa de la latencia.
