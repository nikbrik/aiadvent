# AI Advent Agent Guide

## Project Map

Educational AI Advent demo. `llm_demo/`: Flask serves vanilla web UI; OpenRouter call via explicit REST `httpx.post`.

Canonical documentation:

- `docs/README.md` - documentation index and ownership rules.
- `docs/specs/assignment-1-rest-web-demo.md` - original REST + web + Android demo spec.
- `docs/specs/assignment-2-response-control.md` - response-control assignment spec.
- `docs/agent-notes/llm-demo-assignment-2.md` - implementation decisions, provider notes, debugging workflow, and guardrails.

Tool-specific files stay thin. Do not duplicate long specs in `.cursor/rules`, `.agents`, or assistant-specific dirs; link docs above.

## Caveman Token Mode

Project-local caveman plugin: `.agents/`. Default `/caveman ultra`; Russian prompts -> Russian terse output. Use helpers (`/caveman-commit`, `/caveman-review`, `/caveman-compress`, `/caveman-stats`, `cavecrew-*`) when relevant.

Keep technical terms, code, paths, commands, error strings exact. Drop compression for security warnings, irreversible actions, confused users, or ambiguity risk.

## LLM Demo Rules

When editing `llm_demo/`, preserve:

- Keep the LLM request as explicit REST through `httpx.post`; do not introduce OpenAI SDK, LangChain, Streamlit, or Gradio.
- Keep exactly three control modes: `none`, `api`, `system`.
- Keep the same `user` prompt in every mode. Add control only through API fields or `system` messages.
- Do not split API control into additional UI modes.
- Do not mix API and system controls in one mode.
- Do not auto-fallback when OpenRouter returns HTTP 400 for `response_format`; surface the error in the demo.
- Keep `OPENROUTER_API_KEY` backend-only.

Before response-control changes, read `docs/specs/assignment-2-response-control.md` and `docs/agent-notes/llm-demo-assignment-2.md`.

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

Prefer no-network payload checks before real OpenRouter calls. Run real 3-mode OpenRouter comparisons only with user permission to spend key.
