# Assignment 9: Context Compression

## Goal

Implement history compression for the chat agent:

- keep the last N messages verbatim in the LLM prompt;
- replace older messages with a rolling summary (batch every 10 message records);
- store the summary separately and inject it into the system prompt;
- compare answer quality and token usage with compression off vs on.

## Snapshot Rule

Day 9 may replace previous-day UI and demo flows. Keep only what is needed to demonstrate context compression and token savings.

Required to preserve:

- Flask backend and vanilla browser UI in `llm_demo/`;
- explicit OpenRouter REST call through `httpx.post`;
- `OPENROUTER_API_KEY` only on the backend;
- JSON persistence per `client_id` cookie;
- local token estimates via `token_counter.py`.

## Compression Algorithm

Environment defaults:

- `CONTEXT_KEEP_RECENT_MESSAGES=6`
- `CONTEXT_COMPRESS_EVERY=10`
- `CONTEXT_COMPRESSION_ENABLED=true`
- `OPENROUTER_MODEL=deepseek/deepseek-v4-flash`

Before each chat call when compression is enabled:

1. While `len(messages) - KEEP_RECENT - summarized_through >= COMPRESS_EVERY`, summarize the next batch of 10 records through a dedicated LLM merge call.
2. Store the merged text in `history_summary` and advance `summarized_through`.
3. Build the chat prompt as: system (with summary block) + `messages[summarized_through:]` + new user message.

When compression is disabled, send the full message history (no summary block).

## Token Accounting

Track per turn:

- `history_tokens_full` — entire stored transcript;
- `history_tokens_sent` — transcript portion actually sent;
- `prompt_tokens_full_estimated` — estimate if full history were sent;
- `prompt_tokens_estimated` — estimate for the payload actually sent;
- `summarization_tokens_estimated` — extra cost from merge-summary calls;
- `tokens_net_saved = prompt_tokens_full_estimated - prompt_tokens_estimated - summarization_tokens_estimated`.

No preflight context-limit blocking in Day 9.

## Compare Demo

`POST /api/demo/compression-compare` runs the same scripted dialog twice in ephemeral storage (does not overwrite the browser session):

1. remember codeword BLUEFOX, language Kotlin, project Orbit;
2. filler turns about Python;
3. recall question;
4. LLM judge scores both answers against ground truth;
5. return token and quality comparison.

## API

- `GET /api/chat` — messages, summary, compression state, token stats;
- `POST /api/chat` — `{ "message": "...", "compression": true|false }`;
- `DELETE /api/chat` — clear dialog and stats;
- `POST /api/demo/compression-compare` — ephemeral A/B run.

## Tests

Prefer no-network tests with fake LLM functions. Cover batch compression, prompt selection, token delta, judge parsing, persistence of summary fields, and compare endpoint shape.
