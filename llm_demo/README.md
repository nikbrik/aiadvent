# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет сообщение в Python backend, backend-агент делает явный REST POST через `httpx` к OpenRouter.

Текущий снапшот реализует День 6: первый агент с постоянной памятью.

## Что внутри

- `server.py` - Flask routes `/`, `/api/chat`, `/api/chat/new`.
- `agent.py` - `ChatAgent` и file-based memory store.
- `llm_client.py` - низкоуровневый REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` - vanilla HTML/JS chat UI.
- `static/style.css` - адаптивные стили для desktop и Android Chrome.

Спецификации и агентские заметки вынесены в `../docs/`.

## День 6

Backend ставит `client_id` cookie и хранит память в `data/clients/<client_id>.json`.

Agent сохраняет:

- текущие сообщения чата;
- summary текущего чата;
- summaries прошлых чатов;
- факты о пользователе;
- выводы/persona notes о пользователе;
- preferred communication style.

Перед основным OpenRouter call agent вставляет память в system prompt. После ответа agent делает второй LLM call, чтобы обновить facts, inferences, style и current summary. Если memory-update JSON сломан, видимый ответ все равно возвращается.

Все agent calls используют OpenRouter model `deepseek/deepseek-v4-flash`.

Жёлтая кнопка `Тестовый сценарий` пошагово отправляет 25 scripted messages от вымышленного Android-разработчика Аркадия Чернова. Сценарий автоматически разбивает сообщения на пять чатов и показывает, как память переносится между темами.

## API

| Method | Path | Описание |
| --- | --- | --- |
| `GET` | `/api/chat` | Вернуть текущий чат и память клиента |
| `POST` | `/api/chat` | Принять `{ "message": "..." }`, вернуть ответ агента |
| `POST` | `/api/chat/new` | Архивировать текущий чат и начать новый |
| `DELETE` | `/api/chat` | Очистить память текущего клиента |
| `POST` | `/api/demo/next` | Отправить следующий scripted demo message |

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
| `OPENROUTER_API_KEY` | Обязательный API-ключ OpenRouter |
| `OPENROUTER_MODEL` | Модель OpenRouter, default `z-ai/glm-4.7-flash` |
| `HOST` | Host Flask, default `0.0.0.0` |
| `PORT` | Port Flask, default `5000` |

## Checks

```bash
python -m py_compile server.py llm_client.py agent.py
git diff --check
```

## Ограничения

В демо нет auth, rate limit, streaming и native Android app. API-ключ хранится только на backend и не передается в frontend.
