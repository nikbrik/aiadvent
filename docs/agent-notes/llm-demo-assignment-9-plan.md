# Day 9 Implementation Plan: Context Compression Demo

This note is an implementation handoff for Assignment 9. The canonical
requirements remain in `docs/specs/assignment-9-context-compression.md`; this
file explains how to finish or review the demo in `llm_demo/`.

## Goal And Acceptance Criteria

Build an agent that manages chat context by compressing old history into a
separate summary while preserving recent messages verbatim.

Acceptance criteria:

- Store the full chat transcript in per-client JSON memory.
- Keep the last `N` messages as normal chat messages in the model prompt.
- Replace older messages with a rolling `history_summary`.
- Update the summary in batches, defaulting to every 10 message records.
- Store summary state separately from `current_chat.messages`.
- Inject the summary into the model request only when compression is enabled.
- Compare answer quality with compression off vs on.
- Compare token usage before vs after compression, including summary overhead.
- Preserve the required stack: Flask backend, vanilla browser UI, explicit
  OpenRouter REST through `httpx.post`, backend-only `OPENROUTER_API_KEY`,
  local token estimates through `token_counter.py`.

## Current Architecture

The demo lives in `llm_demo/`.

- `server.py` owns Flask routes and client cookie handling.
- `agent.py` owns memory loading, chat turns, token accounting, compare demo
  orchestration, and public response shaping.
- `context_compression.py` owns compression config, summary merge prompts,
  history selection, and payload preview helpers.
- `compare_demo.py` owns the deterministic Day 9 A/B scenario and visual
  comparison data.
- `quality_judge.py` owns recall quality checks and LLM judge parsing.
- `token_counter.py` owns local token estimates.
- `llm_client.py` owns the explicit OpenRouter `httpx.post` call.
- `static/index.html` and `static/style.css` own the browser demo UI.

Per-client memory is stored under `llm_demo/data/clients/{client_id}.json`.
The relevant persisted fields are:

- `current_chat.messages`: full user/assistant transcript.
- `history_summary`: compressed representation of older messages.
- `compression.enabled`: current default toggle state.
- `compression.summarized_through`: number of message records represented by
  `history_summary`.
- `compression.updates`: summary merge audit events.
- `compression.pinned_facts`: facts that must survive summary merge in the
  compare demo.
- `turns`: per-turn token and prompt metadata.
- `cumulative`: cumulative token/cost counters.

## Compression Algorithm

Use these defaults unless environment variables override them:

- `CONTEXT_KEEP_RECENT_MESSAGES=6`
- `CONTEXT_COMPRESS_EVERY=10`
- `CONTEXT_COMPRESSION_ENABLED=true`
- `MAX_SUMMARY_CHARS=900`
- `OPENROUTER_MODEL=deepseek/deepseek-v4-flash`

Before each live chat completion:

1. Load client memory and normalize missing compression fields.
2. If `compression` override is present in the request, persist it to
   `memory["compression"]["enabled"]`.
3. If compression is disabled, skip summarization and send full history.
4. If compression is enabled:
   - compute `compressible_end = len(messages) - keep_recent`;
   - while `compressible_end - summarized_through >= compress_every`, take the
     next batch of 10 message records;
   - call the LLM with a dedicated merge-summary prompt;
   - replace `history_summary` with the merged compact summary;
   - preserve pinned facts at the top of the summary;
   - advance `summarized_through` by 10;
   - append an event to `compression.updates`.
5. Select prompt history:
   - compression on: `messages[summarized_through:]`;
   - compression off: all `messages`.
6. Build final chat payload:
   - compression on: system prompt with `Previous conversation summary:` block,
     selected tail messages, current user message;
   - compression off: system prompt without summary block, full history,
     current user message.
7. Append the new user and assistant messages to `current_chat.messages`.
8. Save memory and return public state plus turn metadata.

The summary merge call should be compact and factual. It must preserve names,
codewords, numbers, languages, project names, and explicit decisions. If the
merge call fails or returns empty text, use deterministic fallback summary text
so the demo still progresses.

## API Contracts

### `GET /api/chat`

Returns public chat state:

- `messages`
- `history_summary`
- `compression`
- `compression_config`
- `turns`
- `cumulative`
- `current_turn`
- `model`
- `tokenizer`
- `pricing`
- legacy-session hint fields if needed

### `POST /api/chat`

Request:

```json
{
  "message": "User message",
  "compression": true
}
```

`compression` is optional. If omitted, use persisted/default compression state.

Response includes the normal public chat state plus:

- `reply`
- `metadata`
- `last_turn`
- `current_turn`
- `payload_preview`
- optional `judge` when running internal compare recall

Errors:

- `400` for missing or blank `message`.
- OpenRouter errors mapped through `OpenRouterError.status`.

### `DELETE /api/chat`

Clears the current client JSON memory and returns fresh default public state.

### `POST /api/demo/compression-compare`

Runs the A/B comparison in temporary client memories and must not overwrite the
browser session.

Response shape:

```json
{
  "comparison": {
    "without_compression": {},
    "with_compression": {},
    "tokens_saved": 0,
    "token_breakdown": {},
    "quality_delta": "equivalent_recall",
    "visual": {},
    "verdict": "..."
  }
}
```

Each track should include:

- `compression`
- `answer`
- `judge`
- `summary`
- `tokens`
- `merge_count`
- `script_turns`
- `replay`
- `recall_payload`

## Token Accounting

Track these fields per turn:

- `current_request_tokens`: local estimate for the current user message.
- `history_tokens_full`: full stored transcript token estimate.
- `history_tokens_sent`: token estimate for the history actually sent.
- `prompt_tokens_full_estimated`: counterfactual prompt estimate if full
  history were sent.
- `prompt_tokens_estimated`: prompt estimate for the actual payload.
- `prompt_tokens_actual`: provider prompt usage when returned.
- `response_tokens_estimated`: local estimate for assistant reply.
- `response_tokens_actual`: provider completion usage when returned.
- `summarization_tokens_estimated`: prompt plus completion estimate/usage for
  summary merge calls on this turn.
- `tokens_net_saved`: `prompt_tokens_full_estimated - prompt_tokens_estimated -
  summarization_tokens_estimated`.
- `total_tokens_estimated`: `prompt_tokens_estimated +
  response_tokens_estimated + summarization_tokens_estimated`.
- `total_tokens_actual`: provider total usage when returned.
- `turn_cost_actual` and `turn_cost_estimated` if pricing data exists.

Update cumulative totals after every turn:

- `prompt_tokens_estimated`
- `prompt_tokens_full_estimated`
- `response_tokens_estimated`
- `response_tokens_actual`
- `summarization_tokens_estimated`
- `total_tokens_estimated`
- `total_tokens_actual`
- `tokens_net_saved`
- `cost_actual`
- `cost_estimated`

Do not add Day 9 preflight context-limit blocking. This assignment is about
compression and comparison, not refusal before overflow.

## Compare Demo Scenario

The compare demo should be obvious to a reviewer without manual prompt crafting.

Script:

1. First user message asks the agent to remember:
   - codeword: `BLUEFOX`
   - favorite language: `Kotlin`
   - project: `Orbit`
2. Add 14 short filler questions about Python topics.
3. Final recall question asks for the facts from the first message.

Run the same script twice:

- Track A: compression disabled, full history sent.
- Track B: compression enabled, old records summarized and only tail sent.

The compare run may use canned assistant replies for non-recall filler turns to
keep cost and variance low. The recall turn should call the model. The judge
should evaluate whether `BLUEFOX`, `Kotlin`, and `Orbit` are present. Use a
deterministic fact check as the source of truth and an LLM judge only as
additional commentary/scoring.

Expected visible result:

- both tracks recall all three facts, or the UI clearly reports any missed fact;
- compressed recall prompt sends fewer messages/tokens;
- scenario-level token report includes summary merge overhead;
- verdict states whether compression preserved quality and saved tokens.

## UI Requirements

The first screen should be the working demo, not a marketing page.

Required controls and views:

- chat transcript;
- textarea for user message;
- compression toggle;
- `Отправить`, `Сравнить`, and `Очистить` actions;
- status/error area;
- summary preview showing `history_summary`;
- compression journal showing merge events;
- token cards for last turn;
- cumulative token/cost totals;
- turn table with full history tokens, sent history tokens, prompt estimate,
  and net savings;
- payload preview showing what was sent to the model;
- compare showcase with before/after bars, recall answer cards, fact checklist,
  token reduction, and final verdict.

UX should make the acceptance criteria visible:

- "without compression" means full transcript in prompt;
- "with compression" means summary plus recent tail;
- token savings should be displayed both for the final recall prompt and the
  whole scripted scenario;
- quality should be shown as fact recall, not only as a vague score.

## Tests And Verification

No-network unit tests should use fake LLM functions.

Required test coverage:

- compression triggers after enough records and advances
  `summarized_through`;
- prompt selection keeps only recent tail when compression is enabled;
- compression disabled sends full history and omits summary marker;
- LLM merge replaces prior summary instead of duplicating it;
- fallback summary path still updates summary state;
- pinned facts survive summary merge;
- summary state persists after memory reload;
- per-turn token fields and cumulative totals include summarization overhead;
- compare endpoint returns both tracks, token breakdown, quality delta, visual
  data, and verdict;
- judge parsing handles JSON and invalid judge output safely.

Verification commands:

```bash
git diff --check
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py llm_demo/context_compression.py llm_demo/quality_judge.py
python -m unittest llm_demo.test_context_compression llm_demo.test_agent_persistence
```

Known issue in the current worktree: the root `python -m unittest
llm_demo.test_context_compression llm_demo.test_agent_persistence` command can
fail because `server.py` imports `agent` as a top-level module. The same tests
currently pass when run from `llm_demo/` as:

```bash
python -m unittest test_context_compression test_agent_persistence
```

Before final submission, either fix imports so the root command works or update
the documented test command consistently. Prefer fixing imports without breaking
the direct `cd llm_demo && python server.py` workflow.

## Implementation Boundaries

- Do not introduce OpenAI SDK, LangChain, Streamlit, or Gradio.
- Do not expose `OPENROUTER_API_KEY` to browser code.
- Do not run real OpenRouter calls without explicit user permission.
- Do not add compatibility layers only to preserve older assignment behavior.
- Keep Day 9 focused on context compression, token comparison, and recall
  quality.

## Handoff Checklist

- Backend compression path implemented and covered by fake-LLM tests.
- Compare demo returns a reviewer-friendly A/B JSON object.
- Browser UI makes summary, sent tail, quality, and token savings visible.
- `git diff --check` passes.
- Syntax check passes.
- No-network tests pass from the documented location.
- Real compare run is optional and only with user approval to spend key.
