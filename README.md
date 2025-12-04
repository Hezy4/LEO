# LEO - Local Executive Operator

Local, privacy-first assistant that runs against a local LLM via Ollama, calls tools (Home Assistant, tasks, reminders, web search, email, weather), and remembers context in SQLite.

## What it does
- Runs a local LLM (Ollama) and streams replies.
- FastAPI orchestrator builds prompts with persona + memory, dispatches tool calls, and stores session history.
- Tool registry for tasks/reminders/email/web search/weather plus Home Assistant controls (dry-run fallback).
- SQLite-backed memory for preferences, routines, episodic notes, and tool logs.
- CLI/server scripts for quick testing; optional voice agent harness (wake-word + Whisper + Piper).

## Status & features
- Completed
  - Ollama client helpers (`generate`, `chat`) with streaming support.
  - SQLite schema + stores for preferences, tasks, reminders, episodic memory; persona loader and viewer.
  - Tool adapters: `tasks.create/list`, `reminders.create`, `email.send` (outbox), `web.search` stub, `weather.get`, `homeassistant.set_lights`/`run_scene` with dry-run when no token.
  - FastAPI service exposing `/chat` and `/status`, including session history and tool dispatch.
  - Utility scripts: `init_db.py`, `demo_tools.py`, `run_server.py`, `chat_cli.py`, `show_persona.py`, `voice_agent.py` (experimental).
- Planned
  - Vector/semantic memory retrieval and richer conversation summarization.
  - Additional tools (calendar/scheduling sync, broader Home Assistant coverage, file/system utilities).
  - Frontend clients and auth/multi-user support.
  - Packaging/deployment hardening, tests, and monitoring hooks.

## Quick start
1. Install deps: `pip install -e .`
2. Start Ollama; set `OLLAMA_HOST` and `MODEL_NAME` (default `gpt-oss:20b`).
3. Init the DB (defaults to `var/leo.db`): `python scripts/init_db.py`
4. Seed persona: `python scripts/load_persona.py --user-id henry --display-name "Henry Boes"`
5. Smoke-test the LLM: `python examples/ollama_ping.py`
6. Run the API: `python scripts/run_server.py` (FastAPI on `http://localhost:8000`)
7. Chat from the CLI: `python scripts/chat_cli.py --user-id henry --session-id cli`
   - Or curl: `curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' -d '{"user_id":"henry","message":"Make it comfy."}'`
8. Exercise tools without the LLM: `python scripts/demo_tools.py` (writes outbox to `var/outbox/`)

## Configuration
Set these env vars as needed:
- `OLLAMA_HOST`, `MODEL_NAME`, `OLLAMA_TIMEOUT`
- `DB_PATH` (defaults `var/leo.db`)
- `HA_BASE_URL`, `HA_TOKEN` for real Home Assistant calls (otherwise dry-run)
- `WEATHER_ORG_BASE_URL`, `WEATHER_ORG_API_KEY`, `WEATHER_ORG_API_KEY_HEADER`, `WEATHER_ORG_API_KEY_PARAM`, `WEATHER_ORG_CURRENT_PATH`, `WEATHER_ORG_FORECAST_PATH`
- `PICOVOICE_ACCESS_KEY` and model paths if running the voice agent

## Repo map
- `src/leo/clients/` - Ollama + Home Assistant clients
- `src/leo/orchestrator/` - FastAPI service, prompt builder, session/memory plumbing
- `src/leo/memory/` - SQLite stores for preferences/tasks/reminders/episodes
- `src/leo/tools/` - Tool registry + adapters (tasks, reminders, email, web, weather, HA)
- `src/leo/db/schema.sql` - DB schema used by `scripts/init_db.py`
- `scripts/` - Server, CLI chat, tool demos, persona loader, voice agent
- `examples/ollama_ping.py` - Simple LLM connectivity check
- `data/persona.json` - Default persona traits loaded by `load_persona.py`

## Optional: voice agent
Wake-word + STT + TTS loop using openwakeword, faster-whisper, and Piper:
```
PICOVOICE_ACCESS_KEY=... python scripts/voice_agent.py \
  --porcupine-keyword data/wakeword/hey_leo.ppn \
  --whisper-model small \
  --piper-model /path/to/en_GB-ryan-high.onnx \
  --piper-config /path/to/en_GB-ryan-high.onnx.json
```
Use `--list-devices` for mic discovery; `--manual-trigger` skips the wake word.
