# Assignment 4 implementation notes

Day 4 replaces the Day 3 reasoning-mode UI. Snapshot submissions may replace older behavior.

## Model choice

Use `inclusionai/ling-2.6-flash` by default.

Reason:

- budget model in OpenRouter metadata;
- supports `temperature`, `top_p`, `top_k`;
- no reasoning-mode parameter conflict like DeepSeek V4 thinking mode.
- real OpenRouter check returned HTTP 200 for `temperature` values `0`, `0.7`, `1.2` via provider `Novita`.

`mistralai/mistral-nemo` was considered first, but real OpenRouter probes returned upstream `429` through `DeepInfra`.

Keep the OpenRouter call as explicit REST through `httpx.post`.

## Provider guardrails

Always pass:

```json
{"allow_fallbacks": false, "require_parameters": true}
```

This prevents OpenRouter from silently routing to a provider that ignores requested sampling parameters.

Do not send `include_reasoning=true` for this Day 4 model, because strict parameter checking would require reasoning support.

## UI shape

UI shows:

- one prompt textarea;
- disabled model selector;
- single-run temperature selector;
- compare button that runs exactly `0`, `0.7`, `1.2`;
- three response cards with accuracy, creativity, diversity, and recommended use.

## Testing

Syntax and whitespace:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache python3 -m py_compile llm_demo/server.py llm_demo/llm_client.py
git diff --check
```

No-network backend check should monkeypatch `server.chat_completion` and verify `/api/compare` produces three calls with `temperature` values `0`, `0.7`, `1.2`.
