# Submission snapshot policy

## Context

AI Advent assignments are submitted as repository snapshots. Each day is evaluated from the current repository state at submission time, not as a long-lived backwards-compatible product release.

## Project rule

New assignment work may replace, simplify, or break previous assignment UI/behavior when that helps satisfy the current assignment.

This means:

- Do not preserve earlier assignment flows by default.
- Do not add compatibility layers only to keep old days working.
- It is acceptable for Day N to overwrite Day N-1 modes, labels, prompts, and comparison layout.
- Keep previous assignment specs and notes in `docs/` for historical context.
- Keep enduring engineering constraints unless the user explicitly changes them:
  - LLM calls stay explicit REST via `httpx.post`.
  - `OPENROUTER_API_KEY` stays backend-only.
  - No SDK/LangChain/Streamlit/Gradio unless a future assignment asks for it.
  - Prefer no-network payload checks before spending API key balance.

When an older spec conflicts with the active assignment, the active assignment and this snapshot policy win.
