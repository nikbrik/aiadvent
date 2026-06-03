# Assignment 3 implementation notes

Day 3 intentionally replaces the Day 2-centered UI. The user clarified that daily submissions are repository snapshots, so preserving previous assignment behavior is not required.

## Final shape

Main selector: `reasoning_mode`.

Modes:

| Mode | Purpose |
| --- | --- |
| `direct` | Baseline: send only the task as `user` message. |
| `step` | Add a `system` message with the exact idea `Решай пошагово`. |
| `prompt_chain` | Make two API calls: prompt writer, then solver with the generated prompt. |
| `experts` | Add a `system` message that creates analyst/engineer/critic roles. |

The OpenRouter call remains explicit REST through `httpx.post` in `llm_client.py`. No SDK, LangChain, Streamlit, or Gradio.

## Demo task and scoring

The default task is now a 14-activity PERT/CPM construction scheduling problem sourced from:

```text
https://cpm-pert.com/example-pert-cpm
```

Expected answer:

```text
44 days, critical path A-B-C-E-F-J-L-N.
```

`server.py` uses a local heuristic scorer for demo comparison:

- `44` present -> one point;
- compact uppercase answer contains `ABCEFJLN` -> one point.

This gives a clear "most accurate" result for the default task without spending an extra API call on an LLM judge. It is not a generic evaluator for arbitrary user-edited prompts.

## Prompt-chain behavior

`prompt_chain` spends two completions:

1. `PROMPT_WRITER_SYSTEM_PROMPT` asks the model to write a solver prompt and not solve the task.
2. `PROMPT_CHAIN_SOLVER_SYSTEM_PROMPT` asks the model to solve using the generated prompt.

The frontend shows the generated prompt in single-run mode and in a collapsed details block during comparison.

## Reasoning display

OpenRouter can return native reasoning in `choices[0].message.reasoning` for supported models/providers. `llm_client.py` requests `include_reasoning` and captures both `reasoning` and `reasoning_content`.

Do not assume native reasoning will exist for `deepseek/deepseek-v4-flash`. The UI also renders a visible calculation section from the model's normal content:

- `step`, `prompt_chain`, and `experts` prompts ask for `ХОД РАССУЖДЕНИЯ` and `ИТОГ`;
- `server.py` splits those sections into `visible_reasoning` and `final_answer`;
- `direct` may legitimately show no separate reasoning because it is the no-instruction baseline.

## Testing

Syntax and whitespace:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache python3 -m py_compile llm_demo/server.py llm_demo/llm_client.py
git diff --check
```

No-network backend check should monkeypatch `server.chat_completion` and verify:

- `direct`, `step`, `experts` call the model once;
- `prompt_chain` calls the model twice;
- all modes return `evaluation`.
- all successful results return `visible_reasoning`, `final_answer`, and `reasoning_source`.
