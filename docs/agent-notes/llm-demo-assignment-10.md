# Assignment 10 implementation notes

Day 10 replaces the Day 7 UI with a context-strategy demo cockpit.

## Strategy isolation

`llm_demo/agent.py` defines the strategy registry and keeps separate state for:

- `sliding_window`
- `sticky_facts`
- `branching`
- `profile_summaries`
- `token_cut`
- `context_leveling`
- `conversation_recreation`

The active strategy is selected by `active_strategy`. `ChatAgent.respond()` calls one prompt builder and one updater for that strategy only. Other strategy state remains stored for UI/comparison, but does not enter the active prompt.

## Demo flow

`llm_demo/demo_script.py` contains a 12-message requirements-gathering scenario. The expected retained details are goal, audience, deadline, offline-first, no-ML budget, roles, MVP items, and constraints.

`Branching` uses step 8 as checkpoint, then runs steps 9-10 in `branch_a` and steps 11-12 in `branch_b`.

`Stop run` is implemented as a per-client server-side cancellation flag. It is best-effort: an in-flight OpenRouter request finishes, then `Run active` / `Run all` stops before the next scenario step.

`Profile Memory + History Summaries` keeps the main prompt inspector focused on the user-facing answer, but its aggregate metrics count the auxiliary memory-update LLM call too.

## Checks

No-network tests cover persistence plus strategy behavior:

```bash
python -m unittest llm_demo.test_agent_persistence
```

Syntax and whitespace checks:

```bash
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py
git diff --check
```
