# Assignment 8: Token Accounting

## Goal

Add token accounting to the chat agent and make token growth visible:

- count tokens for the current user request;
- count tokens for the complete dialog history that is sent to the model;
- count tokens for the model response;
- show cumulative token and cost growth across the dialog;
- demonstrate what breaks when the prompt exceeds the model context limit.

## Snapshot Rule

Day 8 may simplify or replace previous-day behavior. Keep only what is needed to demonstrate token accounting.

Required to preserve:

- Flask backend and vanilla browser UI in `llm_demo/`;
- explicit OpenRouter REST call through `httpx.post`;
- `OPENROUTER_API_KEY` only on the backend;
- no OpenAI SDK, LangChain, Streamlit, or Gradio.

Allowed to remove or simplify:

- long-term profile memory;
- archived chats;
- scripted Day 6/7 demo flow;
- old comparison modes;
- any UI that distracts from token/cost behavior.

## Implementation Task

Implement a minimal chat agent focused on tokens.

Before every model call, the backend must estimate the prompt size locally. After the model call, it must read provider usage from OpenRouter when available.

Track these values for every turn:

- `current_request_tokens` - tokens in the newest user message;
- `history_tokens` - tokens in all previous dialog messages included in the next prompt;
- `prompt_tokens_estimated` - local estimate for the full `messages` payload sent to OpenRouter;
- `prompt_tokens_actual` - OpenRouter `usage.prompt_tokens`, if returned;
- `response_tokens_estimated` - local estimate for the assistant response;
- `response_tokens_actual` - OpenRouter `usage.completion_tokens`, if returned;
- `total_tokens_actual` - OpenRouter `usage.total_tokens`, if returned;
- `turn_cost_actual` - OpenRouter `usage.cost`, if returned;
- `turn_cost_estimated` - fallback estimate when provider cost is missing;
- cumulative prompt, response, total tokens, and cost for the dialog.

Use clear names in API responses and UI. If a value is estimated, label it as estimated. If it comes from OpenRouter, label it as actual.

## Token Counter

Add a small token-counting module, for example `llm_demo/token_counter.py`.

Requirements:

- `count_text_tokens(text, model)` counts one text string;
- `count_message_tokens(messages, model)` counts chat messages including role/content overhead;
- no network required for counting;
- tokenizer choice must be documented in code or comments.

Preferred behavior:

- use a real tokenizer if the dependency is available and practical;
- otherwise use a deterministic approximate tokenizer;
- keep the fallback stable enough for tests.

The local estimate does not need to exactly match OpenRouter. The point is to show why the prompt grows and why preflight checks matter.

## Cost Calculation

Prefer OpenRouter usage fields:

- `usage.cost`;
- `usage.cost_details`;
- `usage.prompt_tokens`;
- `usage.completion_tokens`;
- `usage.total_tokens`.

If OpenRouter does not return cost, calculate an estimate with configurable prices:

- `PROMPT_PRICE_PER_1M_TOKENS`;
- `COMPLETION_PRICE_PER_1M_TOKENS`.

If prices are not configured, show tokens without pretending that cost is known.

## Context Limit

Add a configurable context limit:

- environment variable: `TOKEN_CONTEXT_LIMIT`;
- default: a small demo-friendly value, for example `4096`;
- UI must show prompt usage against this limit.

Before sending a request to OpenRouter:

1. Build the exact `messages` array that would be sent.
2. Estimate prompt tokens.
3. Add the planned response budget, for example `max_tokens`.
4. If `prompt_tokens_estimated + max_tokens > TOKEN_CONTEXT_LIMIT`, block the call and return a clear overflow result.

The overflow result must show:

- estimated prompt tokens;
- configured limit;
- planned response budget;
- how far over the limit the request is;
- the fact that the model was not called.

This preflight overflow is enough for the assignment. A real provider overflow call is optional and should be run only with explicit user permission to spend API key balance.

## Required Demo Scenarios

Add UI controls or backend endpoints that make these scenarios easy to run.

### Short Dialog

Two or three short messages.

Expected result:

- low prompt/history token count;
- small or zero visible cost;
- plenty of remaining context.

### Long Dialog

Many turns, or a button that appends/sends a prepared sequence of messages.

Expected result:

- history tokens grow on each turn;
- prompt cost grows because old messages are resent;
- response cost grows with each assistant answer;
- UI shows a per-turn table and cumulative totals.

### Overflow Dialog

A prepared scenario that exceeds `TOKEN_CONTEXT_LIMIT`. It may use a deliberately low limit for the demo or a very large generated message.

Expected result:

- backend detects overflow before the OpenRouter call;
- UI shows a visible error/warning state;
- token table still records the failed turn or shows a separate overflow panel;
- user can see exactly what exceeded the limit.

## UI Requirements

The first screen should be the working token demo, not a landing page.

Show:

- chat messages;
- current request tokens;
- history tokens;
- response tokens;
- prompt tokens vs context limit;
- cumulative total tokens;
- cumulative estimated/actual cost;
- per-turn history table;
- controls for Short, Long, Overflow, and Clear.

Keep the interface focused and simple. Previous assignment controls may be removed.

## API Shape

Exact endpoint names are flexible, but the backend must expose enough data for the UI and tests.

Recommended endpoints:

- `GET /api/chat` returns messages, token stats, context limit, pricing state, and turn history;
- `POST /api/chat` accepts `{ "message": "..." }` and returns the assistant reply plus updated token stats;
- `POST /api/demo/short` resets/runs the short scenario;
- `POST /api/demo/long` resets/runs the long scenario;
- `POST /api/demo/overflow` creates an overflow case without spending OpenRouter tokens;
- `DELETE /api/chat` clears dialog and token stats.

## Tests and Checks

Prefer no-network tests with a fake LLM function.

Cover:

- token counting is deterministic;
- `history_tokens` grows after additional turns;
- actual usage from fake OpenRouter metadata is copied into turn stats;
- estimated response tokens are used when actual usage is missing;
- cost estimate is calculated when prices are configured;
- overflow is blocked before the LLM function is called;
- API returns enough token data for the UI.

Run:

```bash
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py
git diff --check
```

## Acceptance Criteria

The submitted snapshot is acceptable when:

- a user can send normal chat messages and see token stats update;
- the UI clearly separates current request, history, response, and cumulative tokens;
- a long dialog visibly becomes more expensive than a short dialog;
- an overflow scenario clearly shows what breaks and why;
- overflow can be demonstrated without a paid OpenRouter call;
- code keeps the project constraints listed above.
