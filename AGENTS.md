# AI Advent Agent Guide

## Project Map

This repository contains an educational AI Advent demo. The app in `llm_demo/` serves a vanilla web UI from Flask and calls OpenRouter through explicit REST with `httpx.post`.

Canonical documentation:

- `docs/README.md` - documentation index and ownership rules.
- `docs/specs/assignment-1-rest-web-demo.md` - original REST + web + Android demo spec.
- `docs/specs/assignment-2-response-control.md` - response-control assignment spec.
- `docs/agent-notes/llm-demo-assignment-2.md` - implementation decisions, provider notes, debugging workflow, and guardrails.

Tool-specific files must stay thin. Do not duplicate long specs inside `.cursor/rules`, `.agents`, or other assistant-specific locations; link to the docs above.

## LLM Demo Rules

When editing `llm_demo/`, preserve these invariants:

- Keep the LLM request as explicit REST through `httpx.post`; do not introduce OpenAI SDK, LangChain, Streamlit, or Gradio.
- Keep exactly three control modes: `none`, `api`, `system`.
- Keep the same `user` prompt in every mode. Add control only through API fields or `system` messages.
- Do not split API control into additional UI modes.
- Do not mix API and system controls in one mode.
- Do not auto-fallback when OpenRouter returns HTTP 400 for `response_format`; surface the error in the demo.
- Keep `OPENROUTER_API_KEY` backend-only.

Before changing response-control behavior, read `docs/specs/assignment-2-response-control.md` and `docs/agent-notes/llm-demo-assignment-2.md`.

## Commands

Run syntax checks:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/aiadvent-pycache python3 -m py_compile llm_demo/server.py llm_demo/llm_client.py
```

Check whitespace in changed files:

```bash
git diff --check
```

Run the server locally:

```bash
cd llm_demo
HOST=127.0.0.1 PORT=5050 ./.venv/bin/python server.py
```

Prefer no-network payload checks before real OpenRouter calls. Only run real 3-mode OpenRouter comparisons when the user permits spending the key.
