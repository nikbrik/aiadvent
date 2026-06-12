# Project Specification

Last reviewed: 2026-06-12

## 1. Project Snapshot

- Name: AI Advent.
- Current state: Educational Flask + vanilla browser demo for AI Advent Day 9, focused on context compression, token accounting, and A/B recall comparison.
- Primary purpose: Demonstrate a low-level LLM REST call from a Python backend to OpenRouter, with visible chat history compression and token/cost metrics.
- Main users: AI Advent learners, instructors/reviewers, and coding agents maintaining daily assignment snapshots.
- Evidence: `README.md`, `llm_demo/README.md`, `AGENTS.md`, `docs/README.md`, `docs/specs/assignment-9-context-compression.md`, `llm_demo/server.py`, `llm_demo/static/index.html`.
- Inference: `README.md` still says the current snapshot is Day 5, while `llm_demo/README.md`, Day 9 docs, UI, and code show Day 9 behavior.

## 2. Goals

- Goal 1: Preserve a minimal educational web chat where the backend calls OpenRouter through explicit REST using `httpx.post`.
- Goal 2: Show how context compression changes the LLM prompt by replacing older messages with a rolling summary while keeping recent messages verbatim.
- Goal 3: Make local token estimates, summarization overhead, net savings, and A/B quality comparison visible to the learner.
- Goal 4: Keep repository documentation and agent instructions centralized in `docs/` and `AGENTS.md`.
- Evidence: `docs/specs/assignment-9-context-compression.md`, `docs/specs/submission-snapshot-policy.md`, `llm_demo/llm_client.py`, `llm_demo/static/index.html`.

## 3. Non-Goals

- Out of scope: Production authentication, multi-user accounts, hosted deployment configuration, database migrations, SDK-based LLM clients, LangChain, Streamlit, Gradio, or compatibility layers for older assignment UIs.
- Out of scope: Preflight context-limit blocking in Day 9.
- Evidence: `AGENTS.md`, `docs/specs/assignment-9-context-compression.md`, `docs/specs/submission-snapshot-policy.md`.

## 4. Users And Personas

| Persona | Need | Purpose | Evidence |
| --- | --- | --- | --- |
| AI Advent learner | Run a browser chat and observe prompt/token changes | Understand LLM context growth and compression tradeoffs | `README.md`, `llm_demo/README.md`, `llm_demo/static/index.html` |
| Assignment reviewer | Inspect a snapshot against current-day requirements | Confirm Day 9 behavior without requiring old flows | `docs/specs/submission-snapshot-policy.md`, `docs/specs/assignment-9-context-compression.md` |
| Coding agent | Find canonical constraints and implementation notes before editing | Avoid breaking REST/key/security/project documentation rules | `AGENTS.md`, `docs/README.md`, `docs/agent-notes/llm-demo-assignment-9.md` |

## 5. Current Architecture

- Runtime and framework: Python Flask backend; vanilla HTML/CSS/JavaScript frontend.
- Entry points: `llm_demo/server.py` serves `/`, `/api/chat`, `/api/demo/compression-script`, `/api/demo/compression-step`, `/api/demo/compression-compare`, and `/api/demo/current-comparison`.
- Major modules:
  - `llm_demo/server.py`: Flask routes, `client_id` cookie, request/response logging.
  - `llm_demo/agent.py`: `ChatAgent`, JSON memory, turn completion, compression-aware prompt building, compare demos, token/cost aggregation.
  - `llm_demo/context_compression.py`: rolling summary config, merge prompt, fallback summary, prompt history selection, pinned facts.
  - `llm_demo/llm_client.py`: OpenRouter REST client using `httpx.post`.
  - `llm_demo/token_counter.py`: local token estimates via optional `tiktoken` or deterministic char heuristic.
  - `llm_demo/quality_judge.py`: deterministic fact recall plus optional LLM judge parsing.
  - `llm_demo/compare_demo.py`: scripted BLUEFOX/Kotlin/Orbit comparison scenario and visual summary data.
  - `llm_demo/static/index.html` and `llm_demo/static/style.css`: browser UI.
- Configuration: environment variables include `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `CONTEXT_KEEP_RECENT_MESSAGES`, `CONTEXT_COMPRESS_EVERY`, `CONTEXT_COMPRESSION_ENABLED`, `MAX_SUMMARY_CHARS`, `MAX_STORED_MESSAGES`, `MAX_STORED_TURNS`, `PROMPT_PRICE_PER_1M_TOKENS`, and `COMPLETION_PRICE_PER_1M_TOKENS`.
- Build and run commands:
  - `cd llm_demo`
  - `python -m venv .venv`
  - `pip install -r requirements.txt`
  - `python server.py`
  - `python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py llm_demo/context_compression.py llm_demo/quality_judge.py`
- Evidence: `llm_demo/README.md`, `llm_demo/requirements.txt`, `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/context_compression.py`, `llm_demo/llm_client.py`, `llm_demo/token_counter.py`.

## 6. Data, Contracts, And Integrations

- Domain entities: browser client, current chat, message, archived chat, profile, history summary, compression config/state, compression update event, turn stats, cumulative token/cost stats, A/B comparison track, judge result.
- Data stores: per-client JSON files under `llm_demo/data/clients/<client_id>.json`; saved atomically through a temp file and `os.replace`.
- API contracts:
  - `GET /api/chat`: returns public memory with messages, profile, archived chat summaries, history summary, compression state, turns, cumulative totals, payload preview, model, tokenizer, compression config, pricing, and legacy-session hints.
  - `POST /api/chat`: accepts `{ "message": "...", "compression": true|false }`; returns updated state plus reply, metadata, last/current turn, and payload preview.
  - `DELETE /api/chat`: clears the current client's JSON memory.
  - `GET /api/demo/compression-script`: returns scripted demo steps.
  - `POST /api/demo/compression-step`: accepts `{ "step_index": number }`; appends one scripted step to current chat.
  - `POST /api/demo/compression-compare`: runs an ephemeral off/on compression A/B scenario.
  - `POST /api/demo/current-comparison`: compares recall on current history without appending the recall question to chat messages.
- External integrations: OpenRouter chat completions at `https://openrouter.ai/api/v1/chat/completions` with backend-only `OPENROUTER_API_KEY`.
- Schemas and migrations: No formal schema or migrations; memory normalization functions upgrade/clean loaded JSON.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/llm_client.py`, `llm_demo/test_context_compression.py`, `.gitignore`.

## 7. Core Workflows

### Workflow: Normal Chat Turn

- Actor: Learner using browser UI.
- Trigger: User submits a message to `POST /api/chat`.
- Steps: Flask validates JSON and cookie, `ChatAgent` loads memory, optionally compresses old history, builds system/history/user payload, estimates tokens, calls OpenRouter unless a canned demo reply is used, appends user/assistant messages, updates cumulative stats, saves JSON, and returns public state.
- Expected result: UI displays the assistant response, token metrics, prompt preview, summary state, and turn history.
- Evidence: `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/context_compression.py`, `llm_demo/static/index.html`.

### Workflow: History Compression

- Actor: Backend agent.
- Trigger: A chat turn runs with compression enabled and enough old messages exist.
- Steps: While `len(messages) - keep_recent - summarized_through >= compress_every`, the agent sends a merge-summary prompt to the LLM, stores the merged `history_summary`, advances `summarized_through`, records summarization token estimates, and injects the summary into the next system prompt.
- Expected result: Older messages are represented by `Previous conversation summary:` while recent messages remain verbatim.
- Evidence: `docs/specs/assignment-9-context-compression.md`, `llm_demo/context_compression.py`, `llm_demo/agent.py`.

### Workflow: Visible Scripted Demo

- Actor: Learner.
- Trigger: User clicks `Продолжить демо`.
- Steps: UI fetches script steps, posts each step by index, updates the current chat after each response, and finally shows recall and compression visualization.
- Expected result: Current chat grows with scripted messages, compression updates appear in the UI, and final recall demonstrates summary retention.
- Evidence: `llm_demo/static/index.html`, `llm_demo/compare_demo.py`, `llm_demo/agent.py`, `llm_demo/test_context_compression.py`.

### Workflow: A/B Current Chat Comparison

- Actor: Learner.
- Trigger: User clicks `A/B текущий чат`.
- Steps: Backend builds a no-compression recall prompt from full history and a compression recall prompt from summary plus tail, calls the model for both, evaluates deterministic fact recall, returns token/quality comparison, and saves only payload preview/summary state.
- Expected result: UI shows before/after token bars, fact checklist, answers, summary preview, and verdict; chat message count is unchanged.
- Evidence: `llm_demo/agent.py`, `llm_demo/static/index.html`, `llm_demo/test_context_compression.py`.

## 8. Functional Requirements

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| FR-001 | The system shall serve a working browser UI as the first screen at `/`. | `llm_demo/server.py`, `llm_demo/static/index.html` | Observed |
| FR-002 | The system shall keep OpenRouter API calls in the backend and use explicit REST via `httpx.post`. | `AGENTS.md`, `llm_demo/llm_client.py` | Observed |
| FR-003 | The system shall not expose `OPENROUTER_API_KEY` to the browser UI. | `llm_demo/llm_client.py`, `llm_demo/static/index.html` | Observed |
| FR-004 | The system shall persist per-browser memory in JSON selected by an HTTP-only `client_id` cookie. | `llm_demo/server.py`, `llm_demo/agent.py`, `.gitignore` | Observed |
| FR-005 | The system shall support compression on/off per chat request. | `llm_demo/server.py`, `llm_demo/agent.py`, `llm_demo/static/index.html` | Observed |
| FR-006 | The system shall compress old messages in batches while preserving the recent tail in the prompt. | `docs/specs/assignment-9-context-compression.md`, `llm_demo/context_compression.py` | Observed |
| FR-007 | The system shall include `history_summary` in the system prompt only when compression is enabled. | `llm_demo/context_compression.py`, `llm_demo/agent.py`, `llm_demo/test_context_compression.py` | Observed |
| FR-008 | The system shall report local token estimates for full history, sent history, prompt, response, summarization overhead, and net savings. | `llm_demo/agent.py`, `llm_demo/token_counter.py`, `llm_demo/static/index.html` | Observed |
| FR-009 | The system shall provide a scripted Day 9 demo that adds steps to the current chat without clearing existing history. | `llm_demo/compare_demo.py`, `llm_demo/agent.py`, `llm_demo/static/index.html` | Observed |
| FR-010 | The system shall provide an ephemeral compression A/B endpoint that does not overwrite the browser session. | `llm_demo/agent.py`, `llm_demo/server.py`, `llm_demo/test_context_compression.py` | Observed |
| FR-011 | The system shall provide current-history A/B comparison without adding the recall question to chat messages. | `llm_demo/agent.py`, `llm_demo/test_context_compression.py` | Observed |
| FR-012 | The system shall redact sensitive headers in request/response logs. | `llm_demo/http_log.py` | Observed |

## 9. User Stories

- As an AI Advent learner, I want to chat with an LLM through a visible web UI, so that I can see how backend REST calls drive model responses.
- As an AI Advent learner, I want to toggle history compression, so that I can compare full-history prompts with summary-plus-tail prompts.
- As an AI Advent learner, I want token metrics after each turn, so that I can see how context grows and when compression saves tokens.
- As an assignment reviewer, I want no-network tests with fake LLM calls, so that I can verify behavior without spending OpenRouter balance.
- As a coding agent, I want canonical docs and notes, so that I can follow current snapshot rules and avoid reviving old assignment flows.

## 10. Acceptance Criteria

- AC-001: WHEN the browser requests `/`, THE SYSTEM SHALL return the Day 9 chat UI.
- AC-002: WHEN `GET /api/chat` is called with no valid `client_id`, THE SYSTEM SHALL create an HTTP-only `client_id` cookie and return an empty public memory state.
- AC-003: WHEN `POST /api/chat` receives an empty message, THE SYSTEM SHALL return HTTP 400 with an error message.
- AC-004: WHEN `POST /api/chat` receives a valid message and compression is disabled, THE SYSTEM SHALL send full current-chat history without a `Previous conversation summary:` block.
- AC-005: WHEN compression is enabled and at least one full compression batch is available, THE SYSTEM SHALL update `history_summary`, advance `compression.summarized_through`, and record a compression update event.
- AC-006: WHEN compression is enabled for a long chat, THE SYSTEM SHALL send fewer history messages than the full stored transcript while preserving recent messages.
- AC-007: WHEN a turn completes, THE SYSTEM SHALL append both user and assistant messages to per-client JSON memory and update cumulative token stats.
- AC-008: WHEN the Flask process restarts and the browser keeps the same `client_id`, THE SYSTEM SHALL load previous messages from disk into the next prompt.
- AC-009: WHEN `/api/demo/compression-step` is called with a valid step index, THE SYSTEM SHALL append that scripted user/assistant pair to the current chat and return updated compression/token state.
- AC-010: WHEN `/api/demo/current-comparison` is called, THE SYSTEM SHALL return both compressed and uncompressed recall tracks without changing the current chat message count.
- AC-011: WHEN OpenRouter returns usage metadata, THE SYSTEM SHALL copy supported token/cost fields into response metadata and turn stats.
- AC-012: WHEN OpenRouter fails or returns an invalid body, THE SYSTEM SHALL return a structured Flask error instead of exposing a traceback.

## 11. Non-Functional Requirements

| Category | Requirement | Verification | Evidence/Assumption |
| --- | --- | --- | --- |
| Security | API key must remain backend-only and sensitive headers must be redacted in logs. | Inspect `llm_demo/llm_client.py`, `llm_demo/http_log.py`, and browser code. | Evidence: `AGENTS.md`, `llm_demo/llm_client.py`, `llm_demo/http_log.py` |
| Reliability | Memory saves must be atomic to reduce corrupted client JSON files. | Inspect `FileMemoryStore.save`; add tests for corrupted JSON fallback if needed. | Evidence: `llm_demo/agent.py` |
| Performance | Stored messages and turns must be capped by environment-configurable limits. | Inspect `trim_stored_messages` and `trim_stored_turns`; run long fake-LLM test. | Evidence: `llm_demo/agent.py` |
| Maintainability | Assignment specs and agent notes must stay in `docs/`, with tool adapters kept thin. | Inspect `docs/README.md`, `AGENTS.md`, `.cursor/rules/aiadvent-project.mdc`. | Evidence: `docs/README.md`, `AGENTS.md` |
| Usability | UI must show chat, compression state, summary, token savings, cumulative totals, prompt preview, and A/B visualization. | Manual browser smoke test or DOM-level test. | Evidence: `llm_demo/static/index.html`, `llm_demo/static/style.css` |
| Testability | Core compression, persistence, and API behavior must be testable without network calls. | Run `python -m unittest llm_demo.test_context_compression llm_demo.test_agent_persistence`. | Evidence: `llm_demo/test_context_compression.py`, `llm_demo/test_agent_persistence.py` |

## 12. Test Strategy

- Existing tests: `llm_demo/test_context_compression.py` covers compression selection, merge behavior, pinned facts, disabled compression, compare endpoints, visible demo steps, current-history comparison, judge parsing, and API response shape.
- Existing tests: `llm_demo/test_agent_persistence.py` covers message persistence across agent restart, compression state persistence, archive resume helpers, and prompt behavior after resume.
- Syntax check: `python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py llm_demo/context_compression.py llm_demo/quality_judge.py`.
- Whitespace check: `git diff --check`.
- Missing tests: automated browser/UI rendering, corrupted JSON fallback, log redaction assertions, direct OpenRouter error parsing variants, and full real-provider smoke tests.
- Acceptance test mapping: AC-004 through AC-010 are mostly covered by fake-LLM unit/API tests; AC-001 and usability checks need browser/manual coverage.
- Evidence: `llm_demo/README.md`, `docs/agent-notes/llm-demo-assignment-9.md`, `llm_demo/test_context_compression.py`, `llm_demo/test_agent_persistence.py`.

## 13. Risks

| Risk | Impact | Mitigation | Evidence |
| --- | --- | --- | --- |
| Root `README.md` says current snapshot is Day 5 while implementation/docs show Day 9. | New contributors may read stale setup/context. | Update root README to align with Day 9 when documentation cleanup is in scope. | `README.md`, `llm_demo/README.md`, `docs/specs/assignment-9-context-compression.md` |
| Real demos can spend OpenRouter balance through many chat, summary, and judge calls. | Accidental cost. | Keep no-network tests default; require explicit user permission for real calls. | `AGENTS.md`, `llm_demo/README.md`, `docs/agent-notes/llm-demo-assignment-9.md` |
| Summary drift can lose early facts despite pinned-facts safeguards. | Compression demo may produce lower recall quality. | Keep deterministic fact recall checks and pinned facts in scripted demos. | `llm_demo/context_compression.py`, `llm_demo/quality_judge.py`, `llm_demo/compare_demo.py` |
| No formal JSON schema or migration system exists for memory files. | Future schema changes may break old client data. | Continue normalizing loaded memory and add regression tests for legacy states. | `llm_demo/agent.py` |
| UI uses live model calls for normal chat and A/B comparison. | Manual demos may fail when API key/network/provider is unavailable. | Keep fake-LLM tests and clearly surface `OpenRouterError` messages. | `llm_demo/server.py`, `llm_demo/llm_client.py`, `llm_demo/test_context_compression.py` |
| `ChatAgent.start_new_chat` and `resume_chat` helpers exist but current Flask routes do not expose Day 6/7 archive controls. | Older specs may imply endpoints/UI that are not active in Day 9. | Follow snapshot policy; document current API instead of preserving old routes. | `docs/specs/submission-snapshot-policy.md`, `llm_demo/server.py`, `llm_demo/agent.py` |

## 14. Assumptions

- Assumption: The active product scope is the Day 9 repository snapshot, not a cumulative product that must preserve every previous assignment interface.
- Assumption: `docs/specs/project-spec.md` is intended as a repository-current spec, not a replacement for daily assignment specs.
- Assumption: Real OpenRouter calls should not be run during spec refresh unless the user explicitly approves spending API key balance.
- Assumption: The primary local development environment is Python with Flask and `httpx`; `tiktoken` is optional.

## 15. Open Questions

- Open question: Should `README.md` be updated now to say Day 9 instead of Day 5?
- Open question: Should Day 6/7 archive routes (`/api/chat/new`, `/api/chat/resume`) stay unexposed in the Day 9 snapshot, or should they be restored for persistence demonstrations?
- Open question: Should the project add an automated browser test for the Day 9 UI, or are Flask test-client checks sufficient for submissions?
- Open question: Should memory JSON get an explicit schema/version migration document beyond current normalization code?

## 16. Roadmap

- Near term: Align root README with Day 9, add browser smoke coverage for the UI, add tests for log redaction and corrupt JSON fallback, and keep Day 9 docs synchronized with implemented API shape.
- Later: Add an explicit memory schema document, optional UI route for archived chat resume if future assignments need it, and structured fixtures for provider error responses.
