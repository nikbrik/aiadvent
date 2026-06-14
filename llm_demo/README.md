# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет сообщение в Python backend, backend-агент делает явный REST POST через `httpx` к OpenRouter.

Текущий снапшот реализует День 10: переключатель 7 изолированных стратегий управления контекстом и наглядный demo-runner для сравнения.

## Что внутри

- `server.py` - Flask routes `/`, `/api/chat`, `/api/context/*`, `/api/demo/*`.
- `agent.py` - `ChatAgent`, file-based memory store, prompt builders для 7 стратегий.
- `demo_script.py` - 12-step сценарий сбора ТЗ с checkpoint и двумя ветками.
- `llm_client.py` - низкоуровневый REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` - vanilla HTML/JS demo cockpit.
- `static/style.css` - адаптивные стили для desktop и Android Chrome.

Спецификации и агентские заметки вынесены в `../docs/`.

## День 10

Доступные стратегии:

- `Sliding Window` - только последние N сообщений.
- `Sticky Facts / Key-Value Memory` - key-value facts + последние сообщения.
- `Branching` - checkpoint, две независимые ветки, переключение веток.
- `Profile Memory + History Summaries` - профильная память, inferences, текущий summary, summaries архивов.
- `Tokenization and Cut` - обрезка истории по estimated token budget.
- `Context Leveling` - уровни goal/audience/constraints/decisions/open questions/recent focus.
- `Conversation Recreation` - чистый prompt из structured state + текущий запрос.

UI позволяет переключать стратегию, пошагово запускать сценарий, запускать текущую стратегию целиком или прогонять все стратегии. После `Run all` таблица сравнивает финальный ответ, сохраненные/потерянные детали, estimated/actual tokens, cost/time и UX score.

`Run all` делает много OpenRouter calls. Для проверок без расхода ключа используйте unit tests с fake LLM.

## API

| Method | Path | Описание |
| --- | --- | --- |
| `GET` | `/api/chat` | Вернуть активную стратегию, transcript, state, prompt report и comparison |
| `POST` | `/api/chat` | Принять `{ "message": "..." }`, вернуть ответ агента |
| `POST` | `/api/chat/new` | Начать новый чат для активной стратегии |
| `POST` | `/api/chat/resume` | Принять `{ "chat_id": "..." }`, восстановить архивный чат |
| `DELETE` | `/api/chat` | Очистить память текущего клиента |
| `POST` | `/api/context/strategy` | Принять `{ "strategy": "..." }`, переключить стратегию |
| `POST` | `/api/context/checkpoint` | Сохранить checkpoint для branching |
| `POST` | `/api/context/branches` | Создать `branch_a` и `branch_b` |
| `POST` | `/api/context/branch` | Принять `{ "branch_id": "..." }`, переключить ветку |
| `POST` | `/api/demo/reset` | Сбросить demo state |
| `POST` | `/api/demo/next` | Отправить следующий scripted demo message |
| `POST` | `/api/demo/run-active` | Прогнать весь сценарий на активной стратегии |
| `POST` | `/api/demo/run-all` | Прогнать весь сценарий на всех 7 стратегиях |

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
| `OPENROUTER_MODEL` | Модель OpenRouter, default `meta-llama/llama-3-8b-instruct` |
| `HOST` | Host Flask, default `0.0.0.0` |
| `PORT` | Port Flask, default `5000` |

## Checks

```bash
python -m py_compile server.py llm_client.py agent.py
python -m unittest test_agent_persistence
git diff --check
```

## Ограничения

В демо нет auth, rate limit, streaming и native Android app. API-ключ хранится только на backend и не передается в frontend.
