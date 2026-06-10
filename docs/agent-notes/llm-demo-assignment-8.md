# Assignment 8 implementation notes

Day 8 replaces the Day 7 memory/archive UI with a token-accounting chat demo.

## Core modules

- `llm_demo/token_counter.py` — local token estimates (`tiktoken:cl100k_base` when installed, else `approx:chars/4`).
- `llm_demo/agent.py` — minimal chat agent with per-turn stats, cumulative totals, preflight overflow, demo scenarios.
- `llm_demo/server.py` — `GET/POST/DELETE /api/chat`, `POST /api/demo/{short,long,overflow}`.

## Turn stats

Each turn records:

- `current_request_tokens`, `history_tokens`
- `prompt_tokens_estimated`, `prompt_tokens_actual`
- `response_tokens_estimated`, `response_tokens_actual`
- `total_tokens_actual`, `turn_cost_actual`, `turn_cost_estimated`

Overflow turns set `status=overflow`, keep the turn in `turns[]`, and do not call OpenRouter.

## Config

Environment variables:

- `TOKEN_CONTEXT_LIMIT` — default `4096`
- `TOKEN_MAX_TOKENS` — response budget for preflight, default `512`
- `PROMPT_PRICE_PER_1M_TOKENS`, `COMPLETION_PRICE_PER_1M_TOKENS` — optional cost fallback

## Checks

No-network regression:

```bash
python -m unittest llm_demo.test_token_accounting
```

Covers agent stats, cumulative `total_tokens_estimated`, zero-cost actual, and Flask API (`GET /api/chat`, `POST /api/demo/overflow` → 413, `DELETE /api/chat`).

Syntax and whitespace:

```bash
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py
git diff --check
```

Real OpenRouter calls for Short/Long demos only with user permission to spend key. Overflow demo is local-only.
