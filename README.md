# AI Advent

Учебный проект для AI Advent: демо низкоуровневого REST-вызова LLM из Python backend с веб-интерфейсом.

## Структура

- `llm_demo/` - рабочее Flask-демо.
- `docs/` - единый источник спецификаций и заметок.
- `AGENTS.md` - инструкции для Codex и других агентских coding tools.
- `.cursor/rules/` - короткий адаптер для Cursor, без дублирования спецификаций.

## Документация

Начинайте с `docs/README.md`. Спецификации лежат в `docs/specs/`, а отладочные решения для будущих агентских сессий - в `docs/agent-notes/`.

Текущий снапшот: День 5, сравнение разных китайских моделей. См. `docs/specs/assignment-5-model-versions.md` и `docs/agent-notes/llm-demo-assignment-5.md`.

## Запуск демо

```bash
cd llm_demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-..."
python server.py
```

По умолчанию сервер слушает `0.0.0.0:5000`.
