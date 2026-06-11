# Assignment 9 implementation notes

Day 9 builds on the Day 7 agent base with batch history compression and Day 8 token counting.

## Core modules

- `llm_demo/context_compression.py` — batch merge-summary, prompt selection, config.
- `llm_demo/quality_judge.py` — LLM judge for compare demo (`passed`, `score`, `note` JSON).
- `llm_demo/token_counter.py` — local token estimates (unchanged from Day 8).
- `llm_demo/agent.py` — compression-aware turns, cumulative stats, ephemeral compare demo.

## Prompt policy

- Compression **on**: system prompt includes `Previous conversation summary:` block from `history_summary`; only `messages[summarized_through:]` are sent as chat history.
- Compression **off**: full `messages[]` sent; summary block omitted (summary remains in JSON).
- Day 6 per-turn `current_chat.summary` memory updater is **not** used for the prompt path.

## Compare demo cost

Ephemeral A/B run uses two isolated client JSON files. Expect many OpenRouter calls (chat + summarization + judge). Run with user permission to spend key.

## Config

- `CONTEXT_KEEP_RECENT_MESSAGES` — default `6`
- `CONTEXT_COMPRESS_EVERY` — default `10`
- `CONTEXT_COMPRESSION_ENABLED` — default `true`
- `MAX_SUMMARY_CHARS` — default `900`
- `OPENROUTER_MODEL` — default `deepseek/deepseek-v4-flash`

## Checks

```bash
python -m unittest llm_demo.test_context_compression llm_demo.test_agent_persistence
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py llm_demo/context_compression.py llm_demo/quality_judge.py
git diff --check
```

## Notes

- LLM merge **replaces** `history_summary`; concat only on summarization fallback.
- `safe_judge_answer` returns a failure object instead of raising.
- `resume_chat` restores full transcript without injecting archive summary into the prompt path.
- `MAX_STORED_MESSAGES` / `MAX_STORED_TURNS` cap JSON growth (default 200).
- `total_tokens_estimated` includes summarization overhead per turn.
