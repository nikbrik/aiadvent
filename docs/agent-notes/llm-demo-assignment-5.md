# Assignment 5 implementation notes

Day 5 replaces the Day 4 temperature UI. Snapshot submissions may replace older behavior.

## Model choice

Use three strongly different Chinese model labs/scales instead of one model family:

- `qwen/qwen3-8b` for weak/baseline;
- `z-ai/glm-4.7-flash` for medium/productivity;
- `deepseek/deepseek-v4-pro` for strong/frontier-scale.

Reason:

- different labs: Alibaba Qwen, Z.ai, DeepSeek;
- clear scale spread: 8.2B dense, 30B-class MoE, 1.6T total / 49B active;
- clear resource spread: small paid dense model, cheap medium MoE model, frontier-scale paid MoE model;
- all have OpenRouter pages and Hugging Face model cards.

Do not use MiniMax M2.7 as medium here: it is too close to DeepSeek V4 Pro for this assignment's contrast goal.
Do not use `qwen/qwen3-4b:free` for the weak slot: real OpenRouter debugging returned `No endpoints found` with `allow_fallbacks=false`.

Keep the OpenRouter call as explicit REST through `httpx.post`.

## Usage and cost

Always send:

```json
{"usage": {"include": true}}
```

Return `prompt_tokens`, `completion_tokens`, `total_tokens`, `usage.cost`, `duration_ms`, OpenRouter `id`, and routed `model` to the UI.

If `usage.cost` is missing, estimate cost from tokens and static pricing metadata. Mark it with `cost_estimated=true`.

## Minimal request body

Keep Day 5 focused on model comparison, not API-control comparison.

Do not set generation parameters in compare runs:

- no `temperature`;
- no `top_p`;
- no `top_k`;
- no `max_tokens`;
- no `stop`;
- no `response_format`.

Real debugging showed that `max_tokens=350` made MiniMax M2.7 spend the whole budget on mandatory reasoning and return empty visible `content`.

Use `reasoning.exclude=true` only to keep hidden reasoning out of the UI/log response. Do not set `effort`; that would alter reasoning behavior and weaken the assignment comparison.

## Provider guardrails

Always pass:

```json
{"allow_fallbacks": false}
```

Do not pass `require_parameters=true` for Day 5; with a minimal payload it adds no value and can turn provider metadata quirks into assignment-blocking errors.

Do not run real OpenRouter comparisons without user permission to spend API key balance.

## Testing

Syntax and whitespace:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache python3 -m py_compile llm_demo/server.py llm_demo/llm_client.py
git diff --check
```

No-network backend check should monkeypatch `server.chat_completion` and verify `/api/compare` produces three calls with exact model ids:

- `qwen/qwen3-8b`;
- `z-ai/glm-4.7-flash`;
- `deepseek/deepseek-v4-pro`.
