# Задание 5: версии моделей

## Цель

Выполнить один и тот же prompt на трех заметно разных китайских моделях:

- weak: `qwen/qwen3-8b`;
- medium: `z-ai/glm-4.7-flash`;
- strong: `deepseek/deepseek-v4-pro`.

Сравнить:

- качество ответов;
- время ответа;
- количество tokens;
- стоимость запроса;
- ресурсоемкость и назначение модели.

## Реализация в `llm_demo`

Демо отправляет один user prompt в OpenRouter три раза. Отличается только `model`.
Generation parameters не задаются: без `temperature`, `top_p`, `top_k`, `max_tokens`, `stop` и `response_format`.

Минимальный payload:

- `model`;
- `messages`;
- `usage.include`: `true`;
- `reasoning.exclude`: `true`;
- `provider.allow_fallbacks`: `false`.

Модели:

| Tier | Model | Lab | Params | Context | Price / 1M tokens | Links |
| --- | --- | --- | --- | --- | --- | --- |
| weak | `qwen/qwen3-8b` | Alibaba Qwen | 8.2B dense / 8.2B active | 131K | $0.05 input / $0.40 output | <https://openrouter.ai/qwen/qwen3-8b>, <https://huggingface.co/Qwen/Qwen3-8B> |
| medium | `z-ai/glm-4.7-flash` | Z.ai / Zhipu | 30B-class MoE | 203K | $0.06 input / $0.40 output | <https://openrouter.ai/z-ai/glm-4.7-flash>, <https://huggingface.co/zai-org/GLM-4.7-Flash> |
| strong | `deepseek/deepseek-v4-pro` | DeepSeek | 1.6T total / 49B active | 1M | $0.435 input / $0.87 output | <https://openrouter.ai/deepseek/deepseek-v4-pro>, <https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro> |

Контраст выбран специально:

- 8.2B paid dense baseline;
- 30B-class cheap medium;
- 1.6T frontier-scale strong.

Default prompt использует CTO decision case с FAQ, договором и SQL. Такой prompt лучше показывает различия качества: слабая модель чаще теряет ограничения, средняя обычно удерживает таблицу, сильная лучше аргументирует риски и tradeoffs.

## Проверка

Backend показывает эвристику качества, а не universal judge:

- markdown table;
- все 3 задачи: FAQ, договор, SQL;
- все 3 tier labels: weak, medium, strong;
- tradeoff по качеству, скорости, стоимости и ресурсоемкости;
- короткий вывод.
- отсутствие внешних model facts вроде GPT/Claude/Gemini/Llama, потому prompt запрещает выдумывать внешние факты.

OpenRouter usage accounting используется для tokens и cost. Если `usage.cost` отсутствует, backend оценивает стоимость по prompt/completion tokens и известной цене за 1M tokens.

OpenRouter reasoning не ограничивается `effort`, чтобы не мешать непосредственному сравнению моделей. Backend отправляет только `exclude=true`, чтобы не показывать hidden reasoning в UI и логах; token accounting при этом остается в usage.

UI показывает detailed telemetry: routed model id, params, active params, architecture, context, prompt/completion/reasoning/cached tokens, actual `usage.cost`, `cost_details`, static price per 1M tokens, latency, finish reason и ссылки.

Реальные OpenRouter сравнения запускать только с разрешения пользователя, потому что все три модели могут списывать баланс.
