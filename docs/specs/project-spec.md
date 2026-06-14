# Project Specification

Last reviewed: 2026-06-12

## 1. Project Snapshot

- Name: AI Advent / LLM REST Web Demo.
- Current state: Day 7 snapshot. A Flask chat agent persists browser-scoped context to disk and restores it after process restart.
- Primary purpose: Educational demo of a low-level REST LLM call from a Python backend with a vanilla browser UI.
- Main users: AI Advent learners and coding agents maintaining the demo. Inference: instructors or reviewers may also use it to verify assignment behavior.
- Evidence: `README.md`, `llm_demo/README.md`, `docs/specs/assignment-7-context-persistence.md`, `AGENTS.md`, `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/llm_client.py`.

## 2. Goals

- Demonstrate explicit backend-to-OpenRouter REST calls through `httpx.post`.
- Provide a browser chat UI that sends messages to a backend agent and displays replies, memory, archived chats, and metadata.
- Persist current chat messages, summaries, profile memory, archived chat state, and scripted demo progress per browser client.
- Restore the saved context after a Flask restart when the same browser keeps its `client_id` cookie.
- Keep assignment documentation and agent notes centralized in `docs/`.

## 3. Non-Goals

- Native Android app delivery is out of scope for the current snapshot.
- Production authentication, authorization, rate limiting, streaming, deployment automation, and multi-process storage are out of scope.
- Compatibility with older assignment UIs is not required unless a future task asks for it.
- SDK wrappers such as OpenAI SDK, LangChain, Streamlit, and Gradio are out of scope.
- Evidence: `llm_demo/README.md`, `docs/specs/submission-snapshot-policy.md`, `AGENTS.md`.

## 4. Users And Personas

| Persona | Need | Purpose | Evidence |
| --- | --- | --- | --- |
| AI Advent learner | Run a small local LLM chat demo and inspect the request flow | Understand REST-based LLM integration and context persistence | `README.md`, `llm_demo/README.md` |
| Assignment reviewer | Verify Day 7 persistence behavior from repo snapshot | Confirm the demo satisfies the active assignment | `docs/specs/assignment-7-context-persistence.md`, `docs/specs/submission-snapshot-policy.md` |
| Coding agent or maintainer | Quickly find specs, invariants, run commands, and implementation notes | Make safe changes without duplicating docs or breaking constraints | `AGENTS.md`, `docs/README.md` |
| Demo operator | Use the scripted scenario to show memory across topics | Demonstrate facts, inferences, style, summaries, and archived chat recall | `llm_demo/demo_script.py`, `llm_demo/static/index.html` |

## 5. Current Architecture

- Runtime and framework: Python Flask backend with vanilla HTML/CSS/JavaScript frontend.
- Entry points: `llm_demo/server.py` starts Flask and defines routes; `llm_demo/static/index.html` is served at `/`.
- Major modules: `server.py` handles HTTP, cookies, logging hooks, and API routing; `agent.py` owns `ChatAgent`, `FileMemoryStore`, prompt construction, memory updates, archive handling, and public snapshots; `llm_client.py` owns OpenRouter REST calls; `demo_script.py` owns scripted demo messages; `http_log.py` formats/redacts request logs.
- Configuration: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `HOST`, and `PORT`; `client_id` is an HTTP-only `SameSite=Lax` cookie.
- Dependencies: `flask` and `httpx`.
- Build and run commands: create a virtualenv, install `llm_demo/requirements.txt`, set `OPENROUTER_API_KEY`, run `python server.py` from `llm_demo/`; default host and port are `0.0.0.0:5000`.
- Tooling: project-local ast-index MCP config points at `.ast-index/index.db`; `.ast-index/`, `.env`, `.venv/`, and `llm_demo/data/` are gitignored.
- Evidence: `llm_demo/requirements.txt`, `llm_demo/README.md`, `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/llm_client.py`, `.mcp.json`, `.codex/config.toml`, `.gitignore`.

## 6. Data, Contracts, And Integrations

- Domain entities: client, memory, profile, current chat, archived chat, message, summary, demo progress, completion metadata.
- Data stores: file-backed JSON in `llm_demo/data/clients/<client_id>.json`; writes use a temp file plus `os.replace`; invalid or unreadable JSON falls back to default memory.
- Memory shape: `version`, `created_at`, `updated_at`, `demo_progress`, `profile.style`, `profile.facts`, `profile.inferences`, `current_chat.id`, `current_chat.started_at`, `current_chat.summary`, `current_chat.messages`, and `archived_chats`.
- API contracts:
  - `GET /api/chat` returns current messages, profile, current summary, archived chat summaries, and demo metadata.
  - `POST /api/chat` accepts JSON `{ "message": "..." }` and returns reply, updated memory, archived chats, demo progress, and OpenRouter metadata.
  - `POST /api/chat/new` archives the current chat and starts an empty current chat.
  - `POST /api/chat/resume` accepts JSON `{ "chat_id": "..." }` and restores a restorable archived chat as current.
  - `DELETE /api/chat` clears memory for the current client.
  - `POST /api/demo/next` submits the next scripted demo message and may start a new chat at configured steps.
- External integration: OpenRouter Chat Completions endpoint `https://openrouter.ai/api/v1/chat/completions` via explicit `httpx.post`.
- OpenRouter payload: model, messages, usage include flag, and optional temperature, top_p, top_k, max_tokens, stop, response_format, provider, and reasoning fields.
- Model behavior: the general REST client default and `ChatAgent.agent_options()` both use `meta-llama/llama-3-8b-instruct` for the Day 10 demo.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/llm_client.py`, `llm_demo/demo_script.py`, `llm_demo/test_agent_persistence.py`, `docs/specs/assignment-7-context-persistence.md`.

## 7. Core Workflows

### Workflow: Load Existing Chat

- Actor: Browser user.
- Trigger: UI loads and calls `GET /api/chat`.
- Steps: Flask validates or creates `client_id`, agent loads disk memory, server returns public memory plus demo metadata, UI renders messages and memory panel.
- Expected result: Existing messages and memory are visible after refresh or restart for the same browser cookie.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/static/index.html`, `docs/specs/assignment-7-context-persistence.md`.

### Workflow: Send Message

- Actor: Browser user.
- Trigger: User submits the chat form.
- Steps: UI posts `{ "message": "..." }`; Flask validates JSON; `ChatAgent.respond()` loads memory, builds LLM messages from system memory plus recent current-chat messages, calls OpenRouter, appends user and assistant turns, calls OpenRouter again for memory JSON, applies memory update if valid, saves JSON, and returns reply and metadata.
- Expected result: User sees the assistant reply, updated transcript, updated memory fields, and completion metadata. If memory-update JSON fails, the visible reply still returns with a warning field.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/llm_client.py`, `llm_demo/static/index.html`.

### Workflow: Start New Chat

- Actor: Browser user or scripted demo.
- Trigger: `POST /api/chat/new`, or demo step configured in `DEMO_NEW_CHAT_STEPS`.
- Steps: Agent loads memory, archives current chat if it has messages, creates a fresh current chat, saves memory, returns public state.
- Expected result: Current transcript clears; previous chat appears as an archived summary with a restorable chat id when messages exist.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/demo_script.py`.

### Workflow: Resume Archived Chat

- Actor: Browser user.
- Trigger: UI posts archived `chat_id` to `POST /api/chat/resume`.
- Steps: Agent finds an archived chat with messages, archives the current chat if needed, restores the selected archived chat as current, saves memory, returns public state.
- Expected result: Restored chat messages are visible and are included in the next LLM prompt; other archived transcripts stay out of the prompt except as summaries.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/test_agent_persistence.py`, `docs/agent-notes/llm-demo-assignment-7.md`.

### Workflow: Clear Memory

- Actor: Browser user.
- Trigger: UI calls `DELETE /api/chat`.
- Steps: Agent deletes the current client's JSON file and returns default public memory.
- Expected result: UI shows an empty chat and empty memory for that client.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/static/index.html`.

### Workflow: Scripted Demo

- Actor: Demo operator.
- Trigger: UI calls `POST /api/demo/next`.
- Steps: Server reads demo progress, starts a new chat at steps 6, 11, 16, and 21, sends the next scripted message through the same agent path, increments progress, and returns updated state.
- Expected result: The 25-message scenario demonstrates cross-chat memory and summarization across five chats.
- Evidence: `llm_demo/server.py`, `llm_demo/demo_script.py`, `llm_demo/static/index.html`.

## 8. Functional Requirements

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| FR-001 | The system shall serve the chat UI at `/`. | `llm_demo/server.py`, `llm_demo/static/index.html` | Observed |
| FR-002 | The system shall identify API clients with a UUID `client_id` cookie. | `llm_demo/server.py` | Observed |
| FR-003 | The system shall persist each client's memory as JSON under `llm_demo/data/clients/`. | `llm_demo/agent.py`, `docs/specs/assignment-7-context-persistence.md` | Observed |
| FR-004 | The system shall include restored current-chat messages in the next LLM prompt after restart. | `llm_demo/agent.py`, `llm_demo/test_agent_persistence.py` | Observed |
| FR-005 | The system shall call OpenRouter through explicit REST `httpx.post`. | `llm_demo/llm_client.py`, `AGENTS.md` | Observed |
| FR-006 | The system shall keep `OPENROUTER_API_KEY` on the backend only. | `llm_demo/llm_client.py`, `AGENTS.md` | Observed |
| FR-007 | The system shall reject empty chat messages with a 400 error. | `llm_demo/agent.py`, `llm_demo/server.py` | Observed |
| FR-008 | The system shall expose current chat state through `GET /api/chat`. | `llm_demo/server.py`, `llm_demo/README.md` | Observed |
| FR-009 | The system shall archive the current chat and start a new chat through `POST /api/chat/new`. | `llm_demo/server.py`, `llm_demo/agent.py` | Observed |
| FR-010 | The system shall restore a restorable archived chat through `POST /api/chat/resume`. | `llm_demo/server.py`, `llm_demo/agent.py` | Observed |
| FR-011 | The system shall expose a 25-message scripted demo through `POST /api/demo/next`. | `llm_demo/server.py`, `llm_demo/demo_script.py` | Observed |
| FR-012 | The system shall redact sensitive headers in formatted logs. | `llm_demo/http_log.py` | Observed |

## 9. User Stories

- As an AI Advent learner, I want to send a message from a browser UI to a Python backend, so that I can see a minimal LLM REST integration.
- As an AI Advent learner, I want the same browser session to recover chat messages after a Flask restart, so that I can understand persisted context.
- As a demo operator, I want a scripted multi-topic scenario, so that I can show facts, inferences, style, and summaries being reused across chats.
- As a maintainer, I want assignment docs and implementation notes centralized, so that I can change the active snapshot without chasing duplicated rules.
- As a reviewer, I want no-network persistence tests, so that I can verify context behavior without spending API key balance.

## 10. Acceptance Criteria

- AC-001: WHEN a browser opens `/`, THE SYSTEM SHALL render the Day 7 chat UI from `llm_demo/static/index.html`.
- AC-002: WHEN an API request lacks a valid `client_id` cookie, THE SYSTEM SHALL set a new HTTP-only `client_id` cookie and use it for memory lookup.
- AC-003: WHEN `POST /api/chat` receives a non-JSON body, THE SYSTEM SHALL return HTTP 400 with an error JSON.
- AC-004: WHEN `POST /api/chat` receives an empty message, THE SYSTEM SHALL return HTTP 400 with an error JSON.
- AC-005: WHEN `POST /api/chat` receives a valid message and OpenRouter succeeds, THE SYSTEM SHALL return a non-empty reply and persist the user and assistant messages.
- AC-006: GIVEN saved messages for a client, WHEN the Flask process restarts and the same browser calls `GET /api/chat`, THEN THE SYSTEM SHALL return those messages.
- AC-007: GIVEN saved messages for a client, WHEN the next message is sent after restart, THEN THE SYSTEM SHALL include the saved messages before the new user message in the LLM prompt.
- AC-008: GIVEN a current chat with messages, WHEN `POST /api/chat/new` is called, THEN THE SYSTEM SHALL move the current chat into `archived_chats` and create an empty current chat.
- AC-009: GIVEN an archived chat with messages, WHEN `POST /api/chat/resume` receives its `chat_id`, THEN THE SYSTEM SHALL restore that chat as current and make its messages available to the next prompt.
- AC-010: WHEN memory-update JSON is invalid after a successful main completion, THE SYSTEM SHALL still return the visible reply and include a memory-update warning.
- AC-011: WHEN `DELETE /api/chat` is called, THE SYSTEM SHALL remove the current client's stored memory and return empty public memory.
- AC-012: WHEN logging browser or OpenRouter exchanges, THE SYSTEM SHALL mask authorization and cookie-like sensitive headers.

## 11. Non-Functional Requirements

| Category | Requirement | Verification | Evidence/Assumption |
| --- | --- | --- | --- |
| Reliability | Context persistence shall survive a single Flask process restart for the same browser cookie. | `python -m unittest llm_demo.test_agent_persistence` | `llm_demo/test_agent_persistence.py` |
| Reliability | File saves shall be atomic within the local filesystem. | Code inspection for temp file plus `os.replace` | `llm_demo/agent.py` |
| Security | API keys shall never be exposed to frontend JavaScript. | Inspect `static/index.html` and `llm_client.py` | `llm_demo/static/index.html`, `llm_demo/llm_client.py` |
| Security | Sensitive headers shall be redacted in logs. | Unit or code inspection of `redact_headers` | `llm_demo/http_log.py` |
| Performance | Prompt context shall be bounded by the latest 40 current messages, latest 8 archived summaries, and up to 24 facts/inferences. | Code inspection or unit tests around constants | `llm_demo/agent.py` |
| Performance | OpenRouter calls shall timeout after 180 seconds. | Code inspection or mocked timeout test | `llm_demo/llm_client.py` |
| Maintainability | Assignment specs and notes shall stay in `docs/`; tool-specific files shall stay thin. | Documentation review | `docs/README.md`, `AGENTS.md`, `.cursor/rules/aiadvent-project.mdc` |
| Usability | The UI shall support desktop and narrow mobile widths. | Browser smoke test at desktop and mobile viewport | `llm_demo/static/style.css` |
| Privacy | Client memory shall be deletable from the UI for the current cookie identity. | Manual or API test of `DELETE /api/chat` | `llm_demo/server.py`, `llm_demo/agent.py` |

## 12. Test Strategy

- Existing tests: `llm_demo/test_agent_persistence.py` covers message persistence after agent restart and restoring archived chats without leaking unrelated archived transcripts into the prompt.
- Existing static checks: `python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py`; `git diff --check`.
- Recommended smoke tests: start Flask locally, load `/`, call `GET /api/chat`, send a message, restart Flask, refresh, continue the chat, start a new chat, resume an archive, and clear memory.
- Missing tests: route-level Flask tests for non-JSON bodies and error responses; tests for corrupted JSON fallback; tests for memory-update failure warning; tests for sensitive header redaction; frontend smoke tests for the main UI controls.
- Acceptance test mapping: `test_messages_survive_agent_restart` covers AC-006 and AC-007; `test_archived_chat_can_be_resumed_and_continued` covers AC-008 and AC-009.
- Evidence: `llm_demo/test_agent_persistence.py`, `llm_demo/README.md`, `docs/agent-notes/llm-demo-assignment-7.md`, `AGENTS.md`.

## 13. Risks

| Risk | Impact | Mitigation | Evidence |
| --- | --- | --- | --- |
| Root `README.md` says the current snapshot is Day 5, while active Day 7 docs, UI, and `llm_demo/README.md` say Day 7. | New agents or reviewers may follow stale guidance. | Update root README to Day 7 or point only to docs map. | `README.md`, `llm_demo/README.md`, `docs/specs/assignment-7-context-persistence.md` |
| `.cursor/rules/aiadvent-project.mdc` docs map stops at older assignment docs. | Cursor users may miss Day 4-7 docs. | Refresh adapter while keeping it short. | `.cursor/rules/aiadvent-project.mdc`, `docs/README.md` |
| Day 10 demo pins `meta-llama/llama-3-8b-instruct` in `ChatAgent.agent_options()`. | Operators may expect `OPENROUTER_MODEL` to override agent replies, but the demo keeps a fixed small-context model for presentation consistency. | Keep the fixed model documented, or deliberately switch `agent_options()` to env-driven behavior later. | `llm_demo/README.md`, `llm_demo/agent.py`, `llm_demo/llm_client.py` |
| File-backed memory has no lock or concurrency control. | Concurrent requests for one client could lose updates. | Keep demo single-user/local, or add locking/SQLite if concurrency becomes a requirement. | `llm_demo/agent.py` |
| No authentication or rate limiting. | Public deployment would expose OpenRouter spend and client memory controls. | Treat as local demo only unless auth/rate limit are added. | `llm_demo/README.md` |
| Memory-update call can fail or return invalid JSON. | Profile and summaries may lag behind visible chat. | Current code returns visible reply and surfaces warning; add tests and possibly retry/repair later. | `llm_demo/agent.py` |
| Real OpenRouter calls spend API balance and require network access. | Tests may be flaky or costly if run live. | Prefer no-network mocked checks; ask before running real calls. | `AGENTS.md`, `docs/specs/assignment-7-context-persistence.md` |

## 14. Assumptions

- Assumption: The product is a local educational demo, not a production service.
- Assumption: English is appropriate for this spec because the deep-init default language is English; the UI and many docs remain Russian by design.
- Assumption: Browser-local `client_id` cookie is sufficient identity for the assignment scope.
- Assumption: Historical assignment specs remain useful context but do not define current behavior when they conflict with Day 7 and the snapshot policy.
- Assumption: No external deployment, uptime, latency, or compliance target exists in the repo evidence.

## 15. Open Questions

- Open question: Should root `README.md` be refreshed from Day 5 to Day 7?
- Open question: Should `.cursor/rules/aiadvent-project.mdc` list Day 4-7 docs, or intentionally defer all current docs to `AGENTS.md` and `docs/README.md`?
- Open question: Should `ChatAgent` respect `OPENROUTER_MODEL`, or should its explicit Day 7 model remain fixed?
- Open question: Should persistence remain JSON-only, or should SQLite be introduced if multiple concurrent clients become important?
- Open question: Should the project add route tests and UI smoke tests before the next assignment snapshot?

## 16. Roadmap

- Near term: Align stale README/adapters with Day 7; add route tests for validation and error paths; add tests for corrupted memory and memory-update warnings.
- Near term: Clarify model override behavior in docs or code.
- Later: Add optional SQLite or file locking if concurrent use becomes part of the assignment.
- Later: Add browser-level smoke tests for archive resume, clear memory, and responsive UI.
- Later: Add authentication, rate limiting, and streaming only if a future assignment changes the demo scope.
