# Assignment 6: First Agent

## Goal

Build a simple agent that:

- accepts a user request;
- sends it to an LLM through an API;
- receives the response;
- displays the response in the interface.

The agent must be a separate backend entity, not just one route calling the API. Request/response logic and memory handling are encapsulated in the agent.

## Snapshot Implementation

Day 6 replaces the Day 5 model-comparison UI with a persistent web chat.

The backend identifies the user by a `client_id` cookie and stores memory on disk per client. The agent uses:

- current chat messages;
- current chat summary;
- summarized previous chats;
- saved facts about the user;
- broad inferences/persona notes about the user;
- a style preference summary.

All memory is inserted into the system prompt before the LLM call. The current user message wins over memory. Inferences must be treated as inferences, not confirmed facts.

The active demo also includes a scripted scenario button that sends 25 messages from a fictional Android developer persona across five chats. It demonstrates profile memory, archived summaries, and cross-chat recall.

## Required Interfaces

- `GET /api/chat` returns current chat and memory.
- `POST /api/chat` accepts `{ "message": "..." }` and returns the agent reply plus updated memory.
- `POST /api/chat/new` archives the current chat summary and starts a new chat.
- `DELETE /api/chat` clears memory for the current client.
- `POST /api/demo/next` runs the next scripted demo message.

## Constraints

- Keep OpenRouter calls as explicit REST through `httpx.post`.
- Keep `OPENROUTER_API_KEY` backend-only.
- Do not use OpenAI SDK, LangChain, Streamlit, or Gradio.
- Prefer no-network checks with monkeypatched LLM calls before real OpenRouter calls.
