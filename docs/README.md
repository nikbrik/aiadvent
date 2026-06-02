# Documentation Map

This directory is the source of truth for project documentation.

## Layout

- `specs/assignment-1-rest-web-demo.md` - initial REST/web/Android demo requirements.
- `specs/assignment-2-response-control.md` - response-control assignment requirements.
- `agent-notes/llm-demo-assignment-2.md` - implementation decisions, provider debugging notes, and guardrails for future Codex/Cursor sessions.
- `agent-notes/caveman-install-playbook.md` - detailed LLM playbook for installing JuliusBrussee/caveman into other projects without accidentally invoking Claude hooks.

## Agent Entrypoints

- `../AGENTS.md` is the canonical repository guide for Codex and compatible coding agents.
- `../.cursor/rules/aiadvent-project.mdc` is a Cursor adapter. It should stay short and point back to `AGENTS.md` and this docs directory.

Do not copy long specs into tool-specific files. If a new AI tool needs project context, add a small adapter that references the canonical docs.

The project-level `.agents/` directory is reserved for reusable skills, subagents, commands, and plugin metadata. Do not put assignment specs there.

## Update Rules

- Put assignment requirements in `specs/`.
- Put learned implementation/debugging decisions in `agent-notes/`.
- Keep `llm_demo/README.md` focused on running the demo.
- Update `AGENTS.md` when project-wide commands, invariants, or documentation paths change.
