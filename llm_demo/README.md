# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет prompt и параметры генерации в Python backend, backend делает явный REST POST через `httpx` к OpenRouter.

## Что внутри

- `server.py` - Flask routes `/` и `/api/chat`.
- `llm_client.py` - низкоуровневый REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` - vanilla HTML/JS UI.
- `static/style.css` - адаптивные стили для desktop и Android Chrome.

Спецификации и агентские заметки вынесены в `../docs/`:

- `../docs/specs/assignment-1-rest-web-demo.md`
- `../docs/specs/assignment-2-response-control.md`
- `../docs/agent-notes/llm-demo-assignment-2.md`

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

Откройте на ноутбуке:

```text
http://localhost:5000
```

## Доступ с Android

1. Подключите Mac и телефон к одной Wi-Fi сети.
2. Узнайте IP Mac:

```bash
ipconfig getifaddr en0
```

3. Откройте в Chrome на телефоне:

```text
http://<IP_ноутбука>:5000
```

4. Для видео: введите prompt, измените `temperature`, `top_p` или `top_k`, отправьте запрос и покажите ответ.

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `OPENROUTER_API_KEY` | Обязательный API-ключ OpenRouter |
| `OPENROUTER_MODEL` | Модель, default `deepseek/deepseek-v4-flash` |
| `HOST` | Host Flask, default `0.0.0.0` |
| `PORT` | Port Flask, default `5000` |

## Ошибки

- `OPENROUTER_API_KEY is not set` - экспортируйте ключ перед запуском.
- `OpenRouter returned HTTP 401` - проверьте ключ.
- `OpenRouter returned HTTP 402` - проверьте баланс OpenRouter.
- Телефон не открывает страницу - проверьте Wi-Fi сеть, firewall macOS и что сервер запущен на `0.0.0.0`.

## Ограничения

В демо нет auth, rate limit, истории сообщений, streaming и native Android app. API-ключ хранится только на backend и не передается в frontend.
