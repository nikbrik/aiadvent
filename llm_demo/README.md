# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет сообщение в Python backend, backend-агент делает явный REST POST через `httpx` к OpenRouter.

Текущий снапшот реализует **День 9**: сжатие истории диалога, token accounting и A/B сравнение качества.

## Что внутри

- `server.py` — Flask routes `/`, `/api/chat`, `/api/demo/compression-step`, `/api/demo/current-comparison`, `/api/demo/compression-compare`.
- `agent.py` — `ChatAgent` с batch compression, per-turn token stats, visible demo steps, compare demo.
- `context_compression.py` — merge-summary, выбор messages для prompt.
- `quality_judge.py` — LLM-judge для compare demo.
- `token_counter.py` — локальная оценка токенов без сети.
- `llm_client.py` — REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` — vanilla HTML/JS chat UI.
- `static/style.css` — адаптивные стили.

Спецификации и агентские заметки вынесены в `../docs/`.

## День 9

Агент хранит полную историю в JSON для UI. В OpenRouter prompt при включённом сжатии:

1. старые сообщения (батчами по 10) сворачиваются в `history_summary` через отдельный LLM-вызов;
2. в prompt попадают summary block в system + последние **6** сообщений + новый user message;
3. UI показывает tokens full vs sent, net savings, payload preview.

Кнопка **Продолжить демо** добавляет 56 scripted turns в текущий чат по шагам, без очистки истории: стартовые факты, 54 разные учебные реплики и recall. Кнопка **A/B текущий чат** сравнивает recall по накопленной истории: без сжатия отправляется вся история, со сжатием — `history_summary` + хвост сообщений. Ephemeral `/api/demo/compression-compare` оставлен как no-session A/B endpoint.

По умолчанию модель **`deepseek/deepseek-v4-flash`**.

## Запуск

```bash
cd llm_demo
cp .env.example .env
# OPENROUTER_API_KEY=...
python server.py
```

Откройте `http://127.0.0.1:5000/`.

## Тесты (без сети)

```bash
python -m unittest llm_demo.test_context_compression llm_demo.test_agent_persistence
python -m py_compile llm_demo/server.py llm_demo/llm_client.py llm_demo/agent.py llm_demo/token_counter.py llm_demo/context_compression.py llm_demo/quality_judge.py
```

## Переменные окружения

- `OPENROUTER_API_KEY` — ключ OpenRouter (только backend).
- `OPENROUTER_MODEL` — default `deepseek/deepseek-v4-flash`.
- `CONTEXT_KEEP_RECENT_MESSAGES` — default `6`.
- `CONTEXT_COMPRESS_EVERY` — default `10`.
- `CONTEXT_COMPRESSION_ENABLED` — default `true`.
- `MAX_SUMMARY_CHARS` — default `900`.
- `MAX_STORED_MESSAGES`, `MAX_STORED_TURNS` — default `2000`.
- `PROMPT_PRICE_PER_1M_TOKENS`, `COMPLETION_PRICE_PER_1M_TOKENS` — optional cost estimate.

Compare demo и длинный ручной чат расходуют баланс OpenRouter — запускайте только с разрешения.
