Got it, you want a spec for LEO that you can hand to an AI coder and say “build this” instead of micromanaging everything yourself. Reasonable. Let’s define this properly so Codex doesn’t invent garbage.

Below is a **clean, implementation-focused description** of the LEO project.
Use this as the reference doc for generating code.

---

# Project: LEO – Local Executive Operator

## 0. Purpose

LEO is a **local, privacy-preserving personal assistant** that:

* Runs on a local machine (MacBook with M4 Max) using an **OSS LLM via Ollama** (e.g., GPT-OSS-20B).
* Acts as a **general personal assistant** (questions, tasks, reminders, planning).
* Can **control smart-home devices** via an automation backend (e.g., Home Assistant).
* Uses **external memory** (database + vector store) to appear persistent and “remember” user preferences.
* Can call **tools** for:

  * Web search / browsing
  * Calendar & reminders
  * Smart-home actions
  * System-level utilities (scripts, apps, etc.)

The model itself stays frozen; “learning” is handled via external memory & tools.

---

## 1. High-Level Architecture

LEO is a **service-based backend**, exposed via HTTP / WebSocket API.

### Components

1. **LLM Backend**

   * Provider: **Ollama** (running locally)
   * Model: GPT-OSS-20B (or similar)
   * Interface: HTTP API

2. **Orchestrator Service (Core brain)**

   * Language: Python (recommended)
   * Framework: FastAPI (or similar)
   * Responsibilities:

     * Handle user requests (text now, voice later).
     * Retrieve relevant memory.
     * Build prompts for the LLM.
     * Interpret LLM output (including tool calls).
     * Call tools (smart home, web, calendar, etc.).
     * Update memory.

3. **Memory Layer**

   * **Long-term structured memory**: SQLite (or PostgreSQL if overkill is desired).
   * **Semantic memory**: Optional vector DB (e.g., Chroma or FAISS).
   * Types of memory:

     * User preferences
     * Routines & mappings (“movie time” → specific actions)
     * Past conversations / episodes (summarized)
     * Tasks, reminders, notes

4. **Tool Layer (Adapters)**

   * Each tool is a Python module with a clear interface.
   * Categories:

     * **Smart Home**: integration with Home Assistant (REST/WebSocket/MQTT).
     * **Web Search**: wrapper around a search API or local search tools.
     * **Calendar/Reminders**: integration with local calendar or external services.
     * **System Utilities**: run scripts, open apps, etc.

5. **API Layer**

   * External interface for:

     * Frontends (CLI, desktop UI, mobile, web).
     * Voice client in the future.
   * Exposes:

     * `/chat` – for conversational use.
     * `/command` – direct structured commands.
     * `/status` – health, logs, debug.

---

## 2. Core Flows

### 2.1 Inference / Assistant Flow

1. User sends input: `text` (e.g. “Make it comfy in here and remind me to call mom tomorrow.”)
2. Orchestrator:

   * Identifies user, timestamp, context.
   * Queries **Memory Layer** for relevant items:

     * User preferences (e.g. “comfy” = lights 40%, temp 72°F).
     * Open tasks, routines, etc.
   * Constructs a **system prompt** and **message history**, including:

     * Role & rules for LEO.
     * Relevant memory entries.
     * Current user message.
   * Sends request to **LLM (Ollama)** with instruction to use tools in JSON format when needed.
3. LLM responds with either:

   * A **direct reply**, or
   * A **tool call** description (structured JSON), or
   * A mix of both (tool calls + natural language).
4. Orchestrator parses response:

   * Executes any tool calls (smart home, reminders, etc.).
   * Collects tool results and, if needed, calls the LLM again with those results.
5. Orchestrator returns final response to client.
6. Memory Layer is updated (new facts, tasks, summaries, etc.).

---

## 3. LLM Prompting & Tool Protocol

### 3.1 System Prompt Template

LEO runs under a **fixed system prompt** like:

> You are LEO, a local personal assistant running entirely on the user's machine.
> You can answer questions, manage tasks, access tools, and control the smart home via structured tool calls.
> When tools are needed, respond ONLY with JSON in the schema described below.
> When no tools are needed, respond in natural language.

Codex should implement this prompt template in the orchestrator, with placeholders for:

* Inserted memories
* Tool schemas
* Current datetime
* User profile basic info

### 3.2 Tool Call Format

All tool calls use a **standard JSON format**. Example schema:

```json
{
  "type": "tool_call",
  "tool": "homeassistant.set_lights",
  "arguments": {
    "room": "living_room",
    "brightness": 40
  }
}
```

For multiple tools in one turn:

```json
{
  "type": "multi_tool_call",
  "calls": [
    {
      "tool": "homeassistant.set_lights",
      "arguments": { "room": "living_room", "brightness": 40 }
    },
    {
      "tool": "reminders.create",
      "arguments": { "text": "Call mom", "time": "2025-11-21T18:00:00" }
    }
  ]
}
```

When no tools are needed:

```json
{
  "type": "reply",
  "text": "Here's the information you asked for..."
}
```

Codex should implement:

* A **Pydantic model** or similar for validation of LLM outputs.
* A dispatcher that maps `"tool"` names to Python functions.

---

## 4. Memory System Design

### 4.1 Types of Memory

1. **Profile & Preferences**

   * Name, timezone, basic profile.
   * Smart-home preferences (temperature, lighting per room, etc.).
   * Communication style (e.g. default brevity).
   * Stored as rows in relational DB tables.

2. **Episodic Memory (Conversations & Events)**

   * Past interactions, summarized.
   * Each episode:

     * `id`
     * `timestamp`
     * `summary`
     * `full_log_location` (optional)
     * `vector_embedding` (for semantic retrieval)

3. **Semantic Memory**

   * Facts about user:

     * “Henry’s preferred ‘cozy’ scene.”
     * “Henry usually wakes at 8 AM on weekdays.”
   * Stored as text + embedding.

4. **Tasks & Reminders**

   * `id`, `description`, `due_time`, `status`, `tags`, etc.

### 4.2 Memory Retrieval

Given a new user request:

1. Run keyword-based search (e.g. using SQLite `LIKE` or FTS).
2. Optionally run vector search (if the vector DB is enabled).
3. Combine top N items (configurable, e.g. 5–10) into a **memory section** in the prompt:

```text
[MEMORY]
- Pref: Cozy scene → lights 40%, temp 72°F, living room.
- Task: “Call mom” set as weekly Sunday reminder.
- Note: Henry dislikes bright bedroom lights at night.
[/MEMORY]
```

Codex should implement:

* A simple memory manager class with methods:

  * `store_preference(...)`
  * `store_episode(...)`
  * `search_memory(query, limit=10)`
  * `store_task(...)`, `get_tasks(...)`, etc.

---

## 5. Smart Home Integration

Assume **Home Assistant** as the backend.

### 5.1 Integration Strategy

* Use **Home Assistant REST API** or **WebSocket API** from Python.
* Define a `HomeAssistantClient` with methods like:

  * `set_light(room, brightness=None, color=None, state=None)`
  * `set_temperature(room_or_device, value)`
  * `run_scene(name)`
  * `get_status(entity_id)`

The tool calls translate into these methods.

### 5.2 Example Tool Definitions

Tool: `homeassistant.set_lights`

Input:

```json
{
  "room": "living_room",
  "brightness": 40
}
```

Tool: `homeassistant.run_scene`

Input:

```json
{
  "scene_name": "movie_time"
}
```

Codex should:

* Create a configurable mapping from human concepts (e.g. `"living_room"`) to HA entity IDs.
* Store these mappings in a config file or DB table.

---

## 6. Web Access / Search Tool

### 6.1 Web Search Tool Interface

Tool: `web.search`

Input:

```json
{
  "query": "how to get rid of fruit flies",
  "max_results": 3
}
```

Output format (from orchestrator to LLM on second pass):

```text
[WEB_RESULTS]
1. Source: example.com
   Snippet: ...

2. Source: wiki-something.com
   Snippet: ...
[/WEB_RESULTS]
```

Codex should:

* Implement an abstract `WebSearchClient` that can use any backend (e.g. custom engine, API).
* The LLM does not call the internet directly; it requests search via tool calls.

---

## 7. Tasks, Reminders & Scheduling

### 7.1 Tasks

Tool: `tasks.create`

Input:

```json
{
  "description": "Buy groceries",
  "due_time": "2025-11-22T15:00:00",
  "tags": ["errand", "home"]
}
```

This is stored in the memory DB.

### 7.2 Reminders

Two options:

* Local cron-like scheduler (APScheduler in Python).
* Or integration with system reminders / calendar.

Tool: `reminders.create`

Input:

```json
{
  "text": "Call mom",
  "time": "2025-11-21T18:00:00"
}
```

Codex should:

* Store the reminder in DB.
* Register the reminder with the scheduler.
* When triggered, the scheduler calls back into the orchestrator to:

  * Send a notification (stdout / webhook / push to client).

---

## 8. API Specification (External Interface)

### 8.1 `/chat` Endpoint

**Method:** `POST`
**Body:**

```json
{
  "user_id": "henry",
  "message": "Make it comfy in here and remind me to call mom tomorrow.",
  "session_id": "optional-session-id"
}
```

**Response:**

```json
{
  "reply": "Okay, I’ve dimmed the lights and set a reminder to call your mom tomorrow at 6 PM.",
  "actions": [
    {
      "tool": "homeassistant.set_lights",
      "arguments": { "room": "living_room", "brightness": 40 },
      "status": "success"
    },
    {
      "tool": "reminders.create",
      "arguments": { "text": "Call mom", "time": "2025-11-21T18:00:00" },
      "status": "success"
    }
  ]
}
```

### 8.2 `/status` Endpoint

Returns:

* Health of:

  * LLM backend
  * Memory DB
  * Home Assistant connectivity
  * Web search client

---

## 9. Configuration & Environment

### 9.1 Environment Variables

* `OLLAMA_HOST` (e.g. `http://localhost:11434`)
* `MODEL_NAME` (e.g. `gpt-oss:20b`)
* `HA_BASE_URL`
* `HA_TOKEN`
* `DB_PATH`
* `VECTOR_DB_PATH` (optional)

### 9.2 Logging

* Log:

  * Requests
  * Tool calls
  * Errors
  * Summarized conversations
* Avoid storing raw full logs by default for privacy.

---

## 10. Phase 1 Scope (MVP)

Codex should focus on implementing:

1. Orchestrator with:

   * System prompt
   * Simple message history
   * Tool JSON parsing & dispatch
2. Memory Layer (SQLite) with:

   * Preferences
   * Tasks
   * Basic episodic memory (no vector search at first)
3. Tools:

   * `homeassistant.set_lights`
   * `homeassistant.run_scene`
   * `reminders.create`
   * `tasks.create`, `tasks.list`
   * `web.search` (can be stubbed or simple wrapper)
4. `/chat` endpoint

Voice, vector search, fancy UI, etc. can be Phase 2.

---

That’s the spec.

This is enough for an AI coder to scaffold the entire backend and start filling in modules without improvising the design. If you want a follow-up, we can write an actual `project/` folder layout and some starter class/method signatures next, but this is the “deep dive goals & architecture” you asked for.

## Current Codebase Layout

To begin implementing the orchestrator, a foundational Ollama client has been added:

- `src/leo/config.py` – Loads Ollama configuration (host/model/timeout) from environment variables with safe defaults.
- `src/leo/clients/ollama_client.py` – Provides `generate` and `chat` helpers over Ollama’s HTTP API, including optional streaming support.
- `src/leo/clients/home_assistant.py` – Minimal REST client for invoking Home Assistant services (degrades to dry-run when no token is configured).
- `src/leo/db/schema.sql` – SQLite schema describing users, preferences, routines, tasks, reminders, episodic memories, and tool logs.
- `src/leo/db/database.py` – Lightweight utility for initializing and interacting with the SQLite file declared via `DB_PATH`.
- `src/leo/memory/` – Store classes (`PreferenceStore`, `TaskStore`, `ReminderStore`, `EpisodicMemoryStore`) that read/write the SQLite tables and surface structured data back to the orchestrator.
- `src/leo/tools/` – Tool framework (context, registry, task/reminder/email/web adapters) that the orchestrator will invoke when the LLM emits tool calls.
- `src/leo/orchestrator/` – FastAPI service that builds prompts from persona data, injects recent memory (tasks/reminders/episodes), persists session history in SQLite, calls the local LLM, and brokers tool calls (including Home Assistant).
- `examples/ollama_ping.py` – Minimal executable that calls the client to verify local connectivity.
- `scripts/init_db.py` – Convenience script that bootstraps the SQLite database using the bundled schema.
- `data/persona.json` – Default persona traits for the assistant.
- `scripts/load_persona.py` – Loader that inserts persona traits into the `preferences` table for the configured user.
- `scripts/show_persona.py` – Prints the reconstructed persona dictionary for a specific user (useful to confirm preference parsing).
- `scripts/demo_tools.py` – Quick way to exercise the task/reminder/email/web tools through the registry.
- `scripts/run_server.py` – Launches the FastAPI orchestrator via Uvicorn.
- `scripts/chat_cli.py` – Simple terminal interface that talks to the `/chat` endpoint for manual testing.

Install dependencies with `pip install -e .` (uses `pyproject.toml`), start Ollama as described in the spec, and run `python examples/ollama_ping.py` to perform a smoke test of the local LLM endpoint.

To initialize persistence, optionally set `DB_PATH` (defaults to `var/leo.db`) and execute `python scripts/init_db.py`. This will create the parent directory if needed and execute `schema.sql` so the orchestrator can begin reading/writing memory entries. Re-run this command whenever the schema is updated (e.g., after adding conversation history tables) so migrations stay current.

Populate the baseline persona by running:

```
python scripts/load_persona.py --user-id henry --display-name "Henry Boes"
```

The script reads `data/persona.json`, flattens nested keys (e.g. `persona.voice`), and upserts them into the `preferences` table linked to the specified user.

Inspect what the orchestrator will see via:

```
python scripts/show_persona.py --user-id henry
```

For quick manual verification of the stores you can enter a `python` REPL and exercise `TaskStore`, `ReminderStore`, and `EpisodicMemoryStore` as demonstrated in `scripts/show_persona.py`.

### Tool Framework Smoke Test

The default tool registry registers `tasks.create`, `tasks.list`, `reminders.create`, `web.search`, and `email.send`. Run the following to stage entries in the DB/outbox and fetch a web search sample (falls back to a local hint message if the search API is unavailable):

```
python scripts/demo_tools.py
```

Outbox emails are written to `var/outbox/*.json`, making it easy to integrate with a future delivery mechanism. If `HA_BASE_URL`/`HA_TOKEN` are set, the Home Assistant tools will issue real service calls; otherwise they return a “dry_run” payload so you can observe what would be executed.

### Orchestrator API

Launch the HTTP server:

```
python scripts/run_server.py
```

This starts FastAPI on `http://localhost:8000`. Two endpoints are exposed:

- `POST /chat` – Accepts `{ "user_id": "henry", "message": "Make it comfy.", "session_id": "living-room" }` and returns `{ "reply": "...", "actions": [...] }`. If the model emits a tool call JSON blob (or structured `tool_calls` payload), the orchestrator executes it via the registry, records the outcome in `actions`, feeds the tool result back to the LLM, and returns the final natural-language reply. Supplying a `session_id` keeps conversational history around future turns.
- `GET /status` – Lightweight health report covering the LLM backend, SQLite memory access, and tool registry initialization.

Example request once the server is running:

```
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "henry", "message": "Add a task to plan the holiday party."}'
```

Expect a structured JSON response with an assistant reply and any tool executions the model initiated.

Session turns are persisted inside the SQLite database (`conversation_sessions` / `conversation_messages`). Clearing any troublesome history is as easy as deleting rows for the affected session ID.

### CLI Chat Client

Once the server is running, you can stay in the terminal and chat without crafting curl requests:

```
python scripts/chat_cli.py --user-id henry --session-id cli
```

Arguments:

- `--base-url` – Override the orchestrator URL if it is not on `http://localhost:8000`.
- `--user-id` – User context for the request; default is `henry`.
- `--session-id` – Session key that keeps history between turns (defaults to `cli`).
- `--quiet` – Only print the final assistant reply (hide tool action logs).

Type `exit` (or press Ctrl+C/Ctrl+D) to leave the chat.

### Home Assistant Integration

Configure the following environment variables before running the server if you’d like real Home Assistant calls instead of dry-run payloads:

- `HA_BASE_URL` – e.g. `http://homeassistant.local:8123`
- `HA_TOKEN` – Long-lived access token generated in Home Assistant

The tool registry exposes `homeassistant.set_lights` and `homeassistant.run_scene`. When tokens are missing, the adapters still succeed but return `mode: dry_run` to show what would have been sent.
