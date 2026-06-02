# Спецификация: LLM через REST (Python) + веб + демо с Android

> Задание AI Advent, неделя 1: низкоуровневый REST-запрос к LLM, ответ в интерфейсе.  
> Ограничение от организатора: без «готовых» обёрток (Streamlit, Gradio, OpenAI SDK и т.п.) — явный HTTP, по аналогии с OkHttp/Retrofit.

---

## 1. Цель

Собрать минимальное решение, которое:

1. Отправляет **REST POST** к LLM API (OpenRouter → модель DeepSeek или аналог).
2. Получает и показывает текст ответа.
3. Позволяет менять параметры генерации (**temperature**, **top_p**, **top_k**) через веб-UI.
4. Демонстрируется на видео с **Android-смартфона** (Chrome), без нативного приложения.

Решение **не** про долгосрочный продакшен: учебный прототип под сдачу челленджа.

---

## 2. Архитектура

```text
┌─────────────────┐
│  Android Chrome │  Wi‑Fi, http://<IP_ноутбука>:5000
└────────┬────────┘
         │ HTTP (HTML, CSS, JS; fetch POST /api/chat)
         ▼
┌─────────────────┐
│  Python backend │  Flask (или FastAPI)
│  static/        │  index.html — слайдеры + поле ввода
└────────┬────────┘
         │ httpx.post (сырой REST)
         ▼
┌─────────────────┐
│  OpenRouter API │  POST /v1/chat/completions
└────────┬────────┘
         │
         ▼
      LLM (deepseek/deepseek-chat)
```

### Слои

| Слой | Технология | Ответственность |
|------|------------|-----------------|
| LLM API | OpenRouter | Инференс модели |
| Backend | Python 3.11+, **httpx** | REST к OpenRouter; прокси для фронта; ключ только на сервере |
| Web | HTML + vanilla JS | UI: промпт, слайдеры, кнопка, вывод ответа |
| Android | Chrome | Только клиент для записи экрана; APK не требуется |

### Что не используем

- Streamlit, Gradio, LangChain
- `openai` Python SDK (скрывает HTTP)
- VPS / Railway (для домашнего демо)
- Нативное Android-приложение (опционально вне scope)

---

## 3. Требования

### 3.1. Функциональные

| ID | Требование |
|----|------------|
| F1 | Пользователь вводит текстовый промпт |
| F2 | Пользователь задаёт `temperature` (0.0–2.0), `top_p` (0.0–1.0), `top_k` (0–100, 0 = не передавать в API) |
| F3 | По кнопке «Отправить» backend выполняет REST-запрос к OpenRouter |
| F4 | Ответ модели отображается на странице |
| F5 | При ошибке API показывается HTTP-код и краткое сообщение (без падения сервера) |
| F6 | На видео видно изменение ответа при разных `temperature` (рекомендация для сдачи) |

### 3.2. Технические (REST)

| ID | Требование |
|----|------------|
| T1 | Вызов LLM только через **httpx** (или `urllib` / `requests`) — явные URL, headers, JSON body |
| T2 | Endpoint: `https://openrouter.ai/api/v1/chat/completions` |
| T3 | Заголовки: `Authorization: Bearer <KEY>`, `Content-Type: application/json` |
| T4 | Тело запроса: `model`, `messages`, `temperature`, `top_p`, опционально `top_k` |
| T5 | Парсинг ответа: `choices[0].message.content` |
| T6 | API-ключ хранится в переменной окружения `OPENROUTER_API_KEY`, не в frontend |

### 3.3. Нефункциональные

| ID | Требование |
|----|------------|
| N1 | Backend слушает `0.0.0.0:5000` для доступа с телефона в локальной сети |
| N2 | Таймаут запроса к OpenRouter: 60 с |
| N3 | Минимум зависимостей: `flask`, `httpx` (или `fastapi`, `uvicorn`, `httpx`) |

---

## 4. Контракты API

### 4.1. Внутренний API (браузер → Python)

**POST** `/api/chat`

Request (`application/json`):

```json
{
  "prompt": "string, обязательный",
  "temperature": 0.7,
  "top_p": 1.0,
  "top_k": 40
}
```

Response 200:

```json
{
  "content": "текст ответа модели"
}
```

Response 4xx/5xx:

```json
{
  "error": "описание ошибки",
  "status": 502
}
```

**GET** `/` — отдаёт `static/index.html`.

### 4.2. Внешний API (Python → OpenRouter)

**POST** `https://openrouter.ai/api/v1/chat/completions`

```json
{
  "model": "deepseek/deepseek-chat",
  "messages": [
    { "role": "user", "content": "<prompt из F1>" }
  ],
  "temperature": 0.7,
  "top_p": 1.0,
  "top_k": 40
}
```

Поле `top_k` не включается в body, если значение `0` (опциональный параметр).

Ответ (успех): стандартный OpenAI-compatible JSON; извлекается `choices[0].message.content`.

---

## 5. Структура проекта (план)

```text
aiadvent/
  llm_rest_web_spec.md      # этот документ
  llm_demo/
    server.py               # Flask + маршруты
    llm_client.py           # httpx → OpenRouter (чистый REST)
    static/
      index.html            # UI + fetch('/api/chat')
      style.css             # опционально
    requirements.txt        # flask, httpx
    .env.example            # OPENROUTER_API_KEY=
    README.md               # запуск и демо с телефона
```

---

## 6. UI (веб)

### Элементы

- Поле ввода: промпт (многострочное).
- Слайдер `temperature`: 0.0–2.0, шаг 0.1, default 0.7.
- Слайдер `top_p`: 0.0–1.0, шаг 0.05, default 1.0.
- Слайдер `top_k`: 0–100, шаг 1, default 40 (0 = выкл.).
- Кнопка «Отправить».
- Блок ответа (текст) + индикатор загрузки.

### Поведение

- `fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: ... })`
- Без фреймворков на фронте (vanilla JS).

---

## 7. Конфигурация и запуск

### Переменные окружения

| Переменная | Описание |
|------------|----------|
| `OPENROUTER_API_KEY` | Ключ OpenRouter (обязательно) |
| `OPENROUTER_MODEL` | Опционально, default `deepseek/deepseek-chat` |
| `HOST` | default `0.0.0.0` |
| `PORT` | default `5000` |

### Запуск (локально)

```bash
cd llm_demo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-..."
python server.py
```

### Доступ с Android

1. Mac и телефон в одной Wi‑Fi.
2. Узнать IP Mac: `ipconfig getifaddr en0` (или аналог).
3. На телефоне: `http://<IP>:5000`.
4. Запись экрана: ввод промпта → смена слайдеров → ответ.

**Запасной вариант:** туннель `ngrok http 5000`, если LAN недоступен.

---

## 8. Безопасность (учебный контур)

- Секретный ключ **только** на backend.
- Не коммитить `.env` (добавить в `.gitignore`).
- Для публичного стора / продакшена схема потребует auth и rate limit — **вне scope** этой спецификации.

---

## 9. Критерии приёмки (сдача челленджа)

- [ ] В репозитории/архиве есть код с явным `httpx.post` (или эквивалент) к OpenRouter.
- [ ] Видео: запрос → ответ в UI на телефоне (или на десктопе, если без Android).
- [ ] На видео видны параметры (`temperature` и др.) и их изменение.
- [ ] Нет Streamlit / SDK OpenAI в качестве основного способа вызова LLM.
- [ ] Краткий README: как запустить и открыть с телефона.

---

## 10. Вне scope

- Аутентификация пользователей
- История диалога / `assistant` messages в сессии
- Деплой на Railway/VPS
- Нативное Android-приложение (OkHttp)
- Streaming ответа (можно добавить в v2)
- System prompt в UI (можно захардкодить в backend при необходимости)

---

## 11. Риски и митигация

| Риск | Митигация |
|------|-----------|
| Телефон не открывает `:5000` | `0.0.0.0`, проверить firewall macOS, одна Wi‑Fi |
| OpenRouter 401/402 | Проверить ключ и баланс |
| Региональные ограничения модели | Сменить `model` в env |
| Медленный ответ | Таймаут 60 с, спиннер в UI |

---

## 12. Дополнение: Assignment 2

Для задания про контроль ответа LLM см.:

- `llm_demo/ASSIGNMENT-2.md` - исходная постановка.
- `llm_demo/ASSIGNMENT-2-IMPLEMENTATION-SPEC.md` - финальные решения, выбор провайдера, выводы отладки и guardrails для будущих Codex/Cursor сессий.
- `.cursor/rules/llm-demo-assignment-2.mdc` - project rule для Cursor, которая указывает читать implementation spec при работе с `llm_demo/**`.

Ключевой инвариант Assignment 2: один и тот же `user` prompt во всех режимах; контроль добавляется только через API-поля или system message.

## 13. Версия

| Поле | Значение |
|------|----------|
| Документ | v1.0 |
| Дата | 2026-06-01 |
| Статус | Спецификация (реализация — следующий шаг) |
