# Assignment 7: Context Persistence

## Goal

Add context persistence to the agent:

- store the dialog history (`messages`) in JSON or SQLite;
- load the saved history when the agent/application starts again;
- continue the dialog as if the agent had not been stopped.

## Snapshot Implementation

Day 7 keeps the Day 6 Flask chat agent and makes the persistence requirement explicit.

The backend identifies a browser session with a `client_id` cookie. Agent memory is stored as JSON in `llm_demo/data/clients/<client_id>.json`, including:

- current chat `messages`;
- current chat summary;
- archived chats with summaries and restorable `messages`;
- facts, inferences, and style preference;
- scripted demo progress.

Every `GET /api/chat` and `POST /api/chat` loads the JSON file through `FileMemoryStore`. A restart creates a new `ChatAgent` instance, but the same client cookie points to the same JSON file, so the restored `messages` are inserted back into the next LLM prompt.

The UI also allows returning to an archived chat. `POST /api/chat/resume` accepts `{ "chat_id": "..." }`, archives the current chat if needed, restores the selected archived chat as `current_chat`, and lets the user continue that older dialog.

Full archived `messages` are not inserted into unrelated LLM prompts. Other chats contribute only their summaries through `Previous chat summaries`; the complete transcript becomes prompt context only after that chat is restored as the current chat.

## Required Manual Check

1. Start the Flask app.
2. Send a message in the chat.
3. Stop and start the Flask app again.
4. Reopen the same browser session or refresh the page.
5. Continue the dialog and verify that the previous messages are still visible and included in the next agent prompt.
6. Start a new chat, then use `Вернуться` on the archived chat and continue that older dialog.

## Constraints

- Keep OpenRouter calls as explicit REST through `httpx.post`.
- Keep `OPENROUTER_API_KEY` backend-only.
- Do not use OpenAI SDK, LangChain, Streamlit, or Gradio.
- Prefer no-network checks with monkeypatched LLM calls before real OpenRouter calls.
