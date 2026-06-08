# Assignment 6 implementation notes

Day 6 replaces the Day 5 comparison runtime. Historical Day 1-5 docs remain as reference, but active behavior is the first-agent chat.

## Agent and memory

The agent is `ChatAgent` in `llm_demo/agent.py`. It owns the full turn flow:

- load per-client memory;
- build a system prompt from long-term memory;
- call `llm_client.chat_completion`;
- save the user and assistant messages;
- run a second LLM call to update memory.

Memory is durable JSON under `llm_demo/data/clients/`, which is gitignored. Each browser profile gets a `client_id` cookie. There is no auth or multi-user account model.

All agent calls use OpenRouter model `deepseek/deepseek-v4-flash`.

## Prompt policy

The system prompt includes:

- preferred style;
- facts;
- tentative inferences;
- current chat summary;
- previous chat summaries.

Full archived transcripts are not sent to the model. Only capped summaries are included to keep context from growing without bound. Current user input overrides memory. The model is instructed not to present inferences as confirmed facts.

## Memory update

Every successful answer triggers a memory-update LLM call. The updater should return JSON with:

- `style`;
- `facts`;
- `inferences`;
- `current_chat_summary`.

If that JSON is invalid, the visible answer still succeeds and the response includes `memory_update_error`.

## Demo scenario

The yellow UI button calls `POST /api/demo/next`. It advances `demo_progress` through 25 scripted messages from Arkady Chernov, an Android developer with wife Marina, daughter Liza, and cat Barsik. Steps 6, 11, 16, and 21 automatically archive the current chat before sending the next message.

## Cleanup

Day 5 active comparison route/UI/model metadata were removed. Top-level real-run result JSON files were deleted. Historical docs remain.

## Checks

Use no-network monkeypatch checks before spending OpenRouter balance. Syntax and whitespace checks:

```bash
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py
git diff --check
```
