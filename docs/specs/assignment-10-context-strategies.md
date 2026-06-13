# Assignment 10: Context Management Strategies

## Goal

Implement an agent demo with a switcher between isolated context-management strategies and compare their behavior on the same product-requirements scenario.

Required strategies:

- `Sliding Window`
- `Sticky Facts / Key-Value Memory`
- `Branching`

Additional strategies kept or added in this snapshot:

- `Profile Memory + History Summaries`
- `Tokenization and Cut`
- `Context Leveling`
- `Conversation Recreation`

## Snapshot Implementation

The Flask app stores per-client JSON state in `llm_demo/data/clients/<client_id>.json`. Each strategy has its own isolated state under `strategies.<strategy_id>`, and only the active strategy's prompt builder controls what is sent to the model.

The UI exposes strategy tabs, demo controls, a timeline, branch controls, prompt preview, context report, retained/lost details, and a comparison table. `Stop run` sets a per-client server flag, so long `Run active` / `Run all` executions stop between model calls instead of only aborting the browser request. Profile-memory token/cost totals include both the user-facing answer call and the auxiliary memory-update call.

The scripted scenario has 12 messages about collecting a product requirements document for a family task app. Early details are intentionally important in the final answer, so the demo makes context loss visible.

For `Branching`, step 8 creates a checkpoint. Steps 9-10 continue `branch_a`; steps 11-12 switch to `branch_b`.

## Acceptance Checks

1. Open the app.
2. Use strategy tabs to switch between all 7 strategies.
3. Press `Run active` and inspect transcript, context blocks, prompt preview, and retained/lost details.
4. Press `Run all` with an OpenRouter key only when real model calls are allowed.
5. Compare final answers, token usage, and lost details in the comparison table.

## Constraints

- Keep OpenRouter calls as explicit REST through `httpx.post`.
- Keep `OPENROUTER_API_KEY` backend-only.
- Do not use OpenAI SDK, LangChain, Streamlit, or Gradio.
- Prefer fake-LLM tests before spending API key balance.
