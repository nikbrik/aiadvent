# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет сообщение в Python backend, backend-агент делает явный REST POST через `httpx` к OpenRouter.

Текущий снапшот реализует День 8: token accounting, рост стоимости и preflight overflow.

## Что внутри

- `server.py` — Flask routes `/`, `/api/chat`, `/api/demo/*`.
- `agent.py` — `ChatAgent` с per-turn token stats и cumulative totals.
- `token_counter.py` — локальная оценка токенов без сети.
- `llm_client.py` — REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` — vanilla HTML/JS chat UI с token panel.
- `static/style.css` — адаптивные стили.

Спецификации и агентские заметки вынесены в `../docs/`.

## День 8

Перед каждым OpenRouter call backend:

1. собирает exact `messages` payload;
2. считает `current_request_tokens`, `history_tokens`, `prompt_tokens_estimated`;
3. проверяет `prompt + max_tokens` против `TOKEN_CONTEXT_LIMIT`;
4. при overflow блокирует вызов и возвращает детали без траты ключа.

После успешного ответа UI показывает actual usage от OpenRouter (`prompt_tokens`, `completion_tokens`, `cost`) и cumulative totals.

Кнопки demo:

- **Short** — 2–3 коротких сообщения;
- **Long** — длинная серия сообщений, виден рост history/prompt cost;
- **Overflow** — локальный сценарий переполнения без OpenRouter;
- **Clear** — сброс диалога и stats.

## API

| Method | Path | Описание |
| --- | --- | --- |
| `GET` | `/api/chat` | Сообщения, token stats, context limit, turn history |
| `POST` | `/api/chat` | `{ "message": "..." }` → ответ + обновлённые stats |
| `DELETE` | `/api/chat` | Очистить диалог и token stats |
| `POST` | `/api/demo/short` | Короткий demo-сценарий |
| `POST` | `/api/demo/long` | Длинный demo-сценарий |
| `POST` | `/api/demo/overflow` | Overflow без OpenRouter call |

## Запуск

```bash
cd llm_demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-..."
python server.py
```

По умолчанию сервер слушает `0.0.0.0:5000`.

Откройте:

```text
http://localhost:5000
```

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `OPENROUTER_API_KEY` | API-ключ OpenRouter (нужен для Short/Long и обычного чата) |
| `OPENROUTER_MODEL` | Модель OpenRouter, default `deepseek/deepseek-v4-flash` |
| `TOKEN_CONTEXT_LIMIT` | Лимит контекста для preflight, default `4096` |
| `TOKEN_MAX_TOKENS` | Response budget в preflight, default `512` |
| `PROMPT_PRICE_PER_1M_TOKENS` | Опционально: цена prompt для estimated cost |
| `COMPLETION_PRICE_PER_1M_TOKENS` | Опционально: цена completion для estimated cost |
| `HOST` | Host Flask, default `0.0.0.0` |
| `PORT` | Port Flask, default `5000` |

## Checks

```bash
python -m py_compile server.py llm_client.py agent.py token_counter.py
python -m unittest test_token_accounting
git diff --check
```

## Ограничения

В демо нет auth, rate limit и streaming. API-ключ хранится только на backend. Overflow demo не тратит баланс OpenRouter.
