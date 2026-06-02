# Assignment 2 implementation notes

This file records implementation and debugging decisions for future Codex and Cursor sessions.
The assignment spec is in `ASSIGNMENT-2.md`; this file captures what was learned while making the demo work.

## Final shape

The demo must keep one invariant: the `user` prompt is identical across all modes. Control is added only outside the user prompt.

Modes:

| Mode | Messages | Extra API fields |
| --- | --- | --- |
| `none` | `[{ "role": "user", "content": prompt }]` | sampling only: `temperature`, `top_p`, optional `top_k` |
| `api` | `[{ "role": "user", "content": prompt }]` | `max_tokens`, `stop`, `response_format`, pinned OpenRouter provider |
| `system` | `system_message` + same `user` prompt | sampling only |

The UI intentionally has exactly three modes:

1. `Без ограничений`
2. `Контроль через API`
3. `Контроль через system`

Do not split API control into separate UI modes. The user explicitly rejected a 4-mode design.

## Current defaults

- Model: `deepseek/deepseek-v4-flash`
- API mode `max_tokens`: `120`
- API mode `stop` input: `\n6., 6.`
- Parsed stop sequences: `["\n6.", "6."]`
- API mode `response_format`: `{ "type": "json_object" }`
- API mode OpenRouter provider pin:

```json
{
  "order": ["novita"],
  "allow_fallbacks": false,
  "require_parameters": true
}
```

`allow_fallbacks=false` and `require_parameters=true` are intentional. They prevent OpenRouter from silently moving the request to a provider that ignores required API controls. If a provider cannot support the requested parameters, the demo should show an error instead of hiding it.

## Prompt design

The original assignment example included text like "Ответь коротко, только список". That makes the demo less clear because it puts response-control instructions into the user prompt.

The implemented demo prompt removes those restrictions:

```text
Придумай 5 необычных причин, почему робот-бариста внезапно начал писать посетителям философские предсказания на стаканчиках. Для каждой причины добавь атмосферную деталь.
```

This makes the contrast visible:

- baseline tends to add intro text, markdown and longer explanations;
- system mode tends to follow format/length/completion instructions semantically;
- API mode is bounded technically and can end mid-answer when `max_tokens` is reached.

## Provider and model debugging notes

The model was kept as `deepseek/deepseek-v4-flash`. A model change was considered only because the user required `max_tokens` to work. The final fix was provider pinning, not replacing the model.

In this context, "provider" means the inference backend OpenRouter routes to for the same model. DeepInfra and Novita are providers, not replacement models. Pinning a provider can change API-parameter support and rate-limit behavior while keeping the selected model name unchanged.

Provider/model probes during debugging:

| Probe | Result | Decision |
| --- | --- | --- |
| `deepseek/deepseek-v4-flash` through DeepInfra | Worked initially with API controls, then hit a `429` rate limit | Not stable enough for this demo |
| OpenRouter provider `deepseek` | No usable pinned endpoint for this model/control set in this context | Not kept |
| OpenRouter provider `alibaba` | No compatible endpoint when `response_format` and `require_parameters` were required | Not kept |
| OpenRouter provider `novita` | Worked with `max_tokens`, `stop`, `response_format` and `require_parameters` | Final provider pin |
| `openai/gpt-4o-mini` | Probe only. JSON mode rejected the request unless the messages mention JSON | Not kept because adding "JSON" to the user prompt would violate the assignment invariant |

Do not switch to `gpt-4o-mini` just because it is familiar. It changes the model and, for JSON mode, can force prompt wording constraints that conflict with "same user prompt".

Pricing is intentionally not hardcoded here. Model/provider prices change; check current OpenRouter and direct-provider pricing before making a cost argument. For this educational demo, OpenRouter is acceptable. A direct DeepSeek key is mainly a predictability/control decision, not automatically a cost win.

## `response_format` caveats

`response_format={"type":"json_object"}` is included because the assignment asks to demonstrate API-level format control.

Important caveats:

- OpenRouter/provider support is not uniform.
- `require_parameters=true` only helps ensure the provider accepts required parameters; it does not prove the visible text is a perfect JSON document.
- With small `max_tokens`, JSON can be truncated or invalid. That is acceptable for this demo because it demonstrates hard API limits.
- If OpenRouter returns HTTP 400 for `response_format`, do not auto-fallback. The UI should show the error so the limitation is visible in the learning demo.

## `max_tokens` and token accounting

In real runs, `completion_tokens` can be larger than the visible `max_tokens` value with DeepSeek/OpenRouter providers. Treat `completion_tokens` as provider usage accounting, which may include hidden/internal reasoning tokens or provider-specific accounting.

For this demo, use these signals instead:

- `finish_reason=length` shows the technical limit was hit;
- visible output length/character count shows the difference for learners;
- HTTP logs show which fields were actually sent.

## Real run observed during implementation

With the final defaults and provider pin, one browser compare run produced:

| Mode | Finish reason | Observed output |
| --- | --- | --- |
| Baseline | `stop` | about `960 completion_tokens`, `2619` visible characters |
| API | `length` | about `478 completion_tokens`, `340` visible characters |
| System | `stop` | about `479 completion_tokens`, `537` visible characters |

Do not treat these numbers as golden test fixtures. They are useful as a sanity check for the expected direction: baseline is longer; API can truncate; system is concise but instruction-based.

## Testing workflow

Syntax checks:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache python3 -m py_compile llm_demo/server.py llm_demo/llm_client.py
git diff --check -- llm_demo/server.py llm_demo/llm_client.py llm_demo/static/index.html llm_demo/static/style.css
```

`PYTHONPYCACHEPREFIX` is needed in the Codex/macOS environment because default `py_compile` may try to write `.pyc` files under `~/Library/Caches`, outside the writable sandbox.

Run server:

```bash
cd llm_demo
HOST=127.0.0.1 PORT=5050 ./.venv/bin/python server.py
```

Use `./.venv/bin/python`, not bare `python3`, because the system Python did not have Flask installed during debugging.

In Codex sandbox, starting or killing a local listener can require escalation. That is expected and not a code issue.

## No-network backend payload check

Use this style of check to prove that each mode assembles the correct payload without spending API credits:

```bash
cd llm_demo
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache ./.venv/bin/python -c "import json, server; calls=[]; prompt='same user prompt'; payload={'prompt':prompt,'model':'deepseek/deepseek-v4-flash','temperature':0.7,'top_p':1,'top_k':40,'max_tokens':120,'stop':chr(92)+'n6., 6.','response_format':{'type':'json_object'},'system_message':'system rules'}; server.chat_completion=lambda **kw: calls.append(kw) or {'content':'ok'}; [server.run_completion(payload, mode) for mode in ['none','api','system']]; print(json.dumps([{k:v for k,v in call.items() if k in ['messages','max_tokens','stop','response_format','provider']} for call in calls], ensure_ascii=False, indent=2))"
```

Expected shape:

- baseline has only the same `user` message;
- API has the same `user` message plus `max_tokens`, parsed `stop`, `response_format`, `provider`;
- system has `system` + same `user` message and no API control fields.

## Browser testing notes

When using the Codex in-app browser:

- after frontend/backend changes, reload or navigate to `http://127.0.0.1:5050/`;
- use browser locators such as `getByRole` / `getByText` where possible;
- if `reload`, `waitForFunction`, or raw DOM `.click()` are unavailable in the browser wrapper, use `tab.goto(...)`, locator clicks, and polling with `evaluate`;
- avoid new real OpenRouter calls unless the user permits spending the key.

Manual UI checks:

1. Radio shows exactly 3 modes.
2. API panel shows `max_tokens`, `stop`, readonly `response_format`.
3. System panel shows editable prefilled system message.
4. Demo prompt text stays identical between modes.
5. `/api/compare` cards appear in this order: baseline, API, system.
6. Metadata shows `finish_reason` and `completion_tokens` when returned by OpenRouter.

## Implementation guardrails

- Keep the LLM call as explicit REST via `httpx.post`; do not introduce OpenAI SDK, LangChain, Streamlit or Gradio.
- Keep user prompt invariant across modes.
- Do not mix API and system controls in a single mode; it obscures which layer caused the behavior.
- Do not auto-fallback on `response_format` 400.
- If changing provider/model, re-run both checks:
  - no-network payload assembly;
  - one real 3-mode compare with the user's permission.
- If making the demo more "visual", prefer changing the demo prompt and comparison layout, not adding constraints to the user prompt.
