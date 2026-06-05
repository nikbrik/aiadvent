# LLM REST Web Demo

Учебное демо для AI Advent: браузер отправляет задачу и параметры генерации в Python backend, backend делает явный REST POST через `httpx` к OpenRouter.

Текущий снапшот реализует День 5: сравнение ответов разных китайских моделей.

## Что внутри

- `server.py` - Flask routes `/`, `/api/chat` и `/api/compare`.
- `llm_client.py` - низкоуровневый REST-запрос к OpenRouter через `httpx.post`.
- `static/index.html` - vanilla HTML/JS UI.
- `static/style.css` - адаптивные стили для desktop и Android Chrome.

Спецификации и агентские заметки вынесены в `../docs/`:

- `../docs/specs/assignment-1-rest-web-demo.md`
- `../docs/specs/assignment-2-response-control.md`
- `../docs/specs/assignment-3-reasoning-modes.md`
- `../docs/specs/assignment-4-temperature.md`
- `../docs/specs/assignment-5-model-versions.md`
- `../docs/agent-notes/llm-demo-assignment-2.md`
- `../docs/agent-notes/llm-demo-assignment-3.md`
- `../docs/agent-notes/llm-demo-assignment-4.md`
- `../docs/agent-notes/llm-demo-assignment-5.md`

## День 5

UI сравнивает один prompt на трех моделях:

| Tier | Model | Lab | Scale |
| --- | --- | --- | --- |
| weak | `qwen/qwen3-8b` | Alibaba Qwen | 8.2B dense |
| medium | `z-ai/glm-4.7-flash` | Z.ai / Zhipu | 30B-class MoE |
| strong | `deepseek/deepseek-v4-pro` | DeepSeek | 1.6T total / 49B active |

Backend делает три OpenRouter вызова с одинаковым `prompt`. Generation parameters не задаются: без `temperature`, `top_p`, `top_k`, `max_tokens`, `stop` и `response_format`.

Provider routing отправляется без fallback:

```json
{"allow_fallbacks": false}
```

OpenRouter usage accounting включен через `{"usage":{"include":true}}`. Hidden reasoning исключается из ответа через `{"reasoning":{"exclude":true}}`, но учитывается в usage tokens.

Backend показывает:

- качество: эвристика соблюдения prompt;
- скорость: `duration_ms` вокруг `httpx.post`;
- tokens: `prompt_tokens`, `completion_tokens`, `total_tokens`;
- reasoning/cache: `reasoning_tokens`, `cached_tokens`;
- стоимость: `usage.cost` из OpenRouter или оценка по tokens и цене модели;
- детали стоимости: `cost_details`, price per 1M input/output tokens;
- ресурсы модели: total/active params, architecture, context window;
- ссылки на OpenRouter и Hugging Face.

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

4. Для видео: нажмите «Сравнить weak / medium / strong» и покажите три ответа с выводами.

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `OPENROUTER_API_KEY` | Обязательный API-ключ OpenRouter |
| `OPENROUTER_MODEL` | Модель для custom/single run fallback, default `z-ai/glm-4.7-flash` |
| `HOST` | Host Flask, default `0.0.0.0` |
| `PORT` | Port Flask, default `5000` |

## Ошибки

- `OPENROUTER_API_KEY is not set` - экспортируйте ключ перед запуском.
- `OpenRouter returned HTTP 401` - проверьте ключ.
- `OpenRouter returned HTTP 402` - проверьте баланс OpenRouter.
- Телефон не открывает страницу - проверьте Wi-Fi сеть, firewall macOS и что сервер запущен на `0.0.0.0`.

## Ограничения

В демо нет auth, rate limit, истории сообщений, streaming и native Android app. API-ключ хранится только на backend и не передается в frontend.
