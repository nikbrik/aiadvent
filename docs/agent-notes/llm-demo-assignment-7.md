# Assignment 7 implementation notes

Day 7 keeps the Day 6 agent shape and focuses the snapshot on durable context.

## Context storage

The durable context store is `FileMemoryStore` in `llm_demo/agent.py`.

- Storage format: JSON.
- Storage location: `llm_demo/data/clients/<client_id>.json`.
- Client identity: `client_id` HTTP-only cookie set by Flask.
- Active transcript key: `current_chat.messages`.
- Restorable archive key: `archived_chats[].messages`.

`ChatAgent.respond()` loads memory before building the LLM prompt, appends the new user/assistant turn after the main completion, and saves the JSON file atomically. `ChatAgent.snapshot()` also loads from disk, so the UI can restore messages after a Flask restart with `GET /api/chat`.

`ChatAgent.resume_chat()` restores an archived chat by `id`. The current chat is archived first if it has messages, then the selected archive becomes `current_chat` and can be continued.

## Restart behavior

A process restart loses Python objects but not `llm_demo/data/clients/*.json`. When the browser keeps the same `client_id` cookie, the new `ChatAgent` instance loads the same JSON file and includes restored `messages` in `build_llm_messages()`.

Full archived transcripts are not sent to the model while another chat is active. `build_system_prompt()` uses only archived summaries under `Previous chat summaries`; full `archived_chats[].messages` are used only after the user restores that chat as the active `current_chat`.

## Checks

No-network restart regression:

```bash
python -m unittest llm_demo.test_agent_persistence
```

Syntax and whitespace checks:

```bash
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py
git diff --check
```
