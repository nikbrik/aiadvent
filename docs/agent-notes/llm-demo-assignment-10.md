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

`Continue` uses persisted `demo_run` state. For `Run active`, it stores the active strategy and last successful scenario step. For `Run all`, it stores the current strategy index, step progress, and completed comparison results. On recoverable OpenRouter errors, demo endpoints return a normal JSON payload with `demo_error` instead of losing the partial run.

The browser uses `/api/demo/start-active`, `/api/demo/start-all`, and `/api/demo/continue-step` for live execution. Each `continue-step` performs at most one scenario LLM call, then the UI re-renders immediately.

After each strategy finishes during live `Run all`, the UI stays on that finished strategy for one render cycle, so the presenter can inspect its final prompt and metrics before the next `continue-step` starts the next strategy.

`Profile Memory + History Summaries` keeps the main prompt inspector focused on the user-facing answer, but its aggregate metrics count the auxiliary memory-update LLM call too.

`Sliding Window` keeps `total_seen_messages` and `discarded_messages_total`, because older messages are physically dropped from its state. The context report uses those counters instead of pretending discarded history is still available to count.

`Tokenization and Cut` uses an estimated 320-token prompt budget for history and truncates an oversized history message with a visible `[truncated by token budget]` marker.

`Branching` comparison results include separate `branch_results` for Branch A and Branch B, so the table can show both final answers instead of scoring only the active branch.

The default agent model is `meta-llama/llama-3-8b-instruct` with `max_tokens=700`. Its 8k context window makes context pressure visible in the demo; very large-context models hide the assignment's failure mode.

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
