"""Deterministic A/B compression compare demo with visual metrics."""

COMPARE_SECRET_PROMPT = (
    "Запомни три факта: кодовое слово BLUEFOX, любимый язык Kotlin, проект Orbit. "
    "Ответь только «OK»."
)
COMPARE_RECALL_PROMPT = (
    "Назови кодовое слово, любимый язык и проект из самого первого сообщения. "
    "Кратко, по пунктам."
)
COMPARE_GROUND_TRUTH = {
    "codeword": "BLUEFOX",
    "language": "Kotlin",
    "project": "Orbit",
}
COMPARE_PINNED_FACTS = [
    "codeword: BLUEFOX",
    "favorite language: Kotlin",
    "project: Orbit",
]
COMPARE_STORY = [
    "Шаг 1 — в начале диалога просим запомнить BLUEFOX / Kotlin / Orbit.",
    "Шаг 2 — 54 разные учебные реплики (шум, история заметно растёт).",
    "Шаг 3 — recall: «что было в первом сообщении?»",
]

_COMPARE_FILLER_TOPICS = [
    ("list comprehensions", "Python collections"),
    ("generators", "lazy iteration"),
    ("tuple vs list", "data structures"),
    ("decorators", "Python functions"),
    ("GIL", "runtime internals"),
    ("asyncio", "concurrency"),
    ("dataclass", "data modeling"),
    ("dict", "hash maps"),
    ("context managers", "resource handling"),
    ("append vs extend", "list operations"),
    ("lambda", "small functions"),
    ("type hints", "static analysis"),
    ("exceptions", "error handling"),
    ("pytest fixtures", "testing"),
    ("mock objects", "testing doubles"),
    ("property-based tests", "quality"),
    ("logging levels", "observability"),
    ("structured logs", "observability"),
    ("retry with backoff", "resilience"),
    ("idempotency keys", "API design"),
    ("pagination", "REST APIs"),
    ("rate limiting", "backend safety"),
    ("caching TTL", "performance"),
    ("cache invalidation", "performance"),
    ("database indexes", "storage"),
    ("transaction isolation", "databases"),
    ("optimistic locking", "concurrency"),
    ("message queues", "architecture"),
    ("dead-letter queues", "messaging"),
    ("feature flags", "release engineering"),
    ("canary rollout", "deployment"),
    ("blue-green deployment", "deployment"),
    ("health checks", "operations"),
    ("Kotlin data classes", "Kotlin"),
    ("sealed interfaces", "Kotlin"),
    ("coroutines", "Kotlin concurrency"),
    ("Flow", "Kotlin streams"),
    ("Orbit MVI", "mobile architecture"),
    ("state reducer", "frontend state"),
    ("side effects", "state management"),
    ("accessibility labels", "frontend quality"),
    ("keyboard navigation", "frontend UX"),
    ("responsive grids", "layout"),
    ("semantic HTML", "web basics"),
    ("CORS", "browser security"),
    ("CSRF", "web security"),
    ("JWT expiry", "auth"),
    ("refresh tokens", "auth"),
    ("PII redaction", "privacy"),
    ("token counting", "LLM apps"),
    ("prompt injection", "LLM safety"),
    ("context windows", "LLM apps"),
    ("summary drift", "LLM memory"),
    ("embedding search", "retrieval"),
]

_COMPARE_PROMPT_TEMPLATES = [
    "Объясни тему «{topic}» ({area}) для junior-разработчика: назначение, риск, практический совет. Дай 4 коротких предложения.",
    "Составь мини-конспект про «{topic}» из области {area}: когда применять, когда не применять, один пример словами. Ответ 4 предложения.",
    "Представь code review: что проверить в теме «{topic}» ({area})? Назови пользу, типичную ошибку и критерий готовности. Пиши кратко.",
    "Сделай карточку знания про «{topic}» ({area}): определение, сигнал к применению, антипример, итог. Без markdown.",
    "Объясни на рабочем примере «{topic}» ({area}): контекст задачи, решение, компромисс, проверка результата. 4 коротких предложения.",
    "Дай практическую заметку про «{topic}» ({area}): зачем нужно, как внедрить, что измерить, где осторожничать.",
]


def compare_script_steps():
    """User/assistant pairs; assistant=None means live LLM (recall turn)."""
    steps = [
        {"user": COMPARE_SECRET_PROMPT, "assistant": "OK"},
    ]
    for index, (topic, area) in enumerate(_COMPARE_FILLER_TOPICS, start=1):
        template = _COMPARE_PROMPT_TEMPLATES[(index - 1) % len(_COMPARE_PROMPT_TEMPLATES)]
        steps.append({
            "user": template.format(topic=topic, area=area),
            "assistant": (
                f"#{index}: {topic} ({area}) — отдельная учебная реплика для demo. "
                f"Смысл: показать практический приём и добавить в историю новый контекст. "
                f"Польза: тема помогает принять более явное инженерное решение. "
                f"Риск: применять {topic} механически без проверки задачи и ограничений. "
                "Проверка: после применения должно стать проще объяснить поведение системы."
            ),
        })
    steps.append({"user": COMPARE_RECALL_PROMPT, "assistant": None})
    return steps


def compare_user_script():
    return [step["user"] for step in compare_script_steps()]


def build_recall_payload(track):
    recall = track.get("recall_payload") or {}
    tokens = track.get("tokens") or {}
    return {
        "prompt_tokens": int(tokens.get("final_prompt_estimated") or 0),
        "prompt_tokens_full": int(tokens.get("final_prompt_full_estimated") or 0),
        "messages_total": int(recall.get("messages_total") or 0),
        "messages_sent": int(recall.get("messages_sent") or 0),
        "summary_chars": int(recall.get("summary_chars") or 0),
    }


def build_token_breakdown(with_track, without_track):
    tokens = with_track.get("tokens") or {}
    without_tokens = without_track.get("tokens") or {}
    prompt_full = int(tokens.get("cumulative_prompt_full_estimated") or 0)
    prompt_sent = int(tokens.get("cumulative_prompt_estimated") or 0)
    summarize = int(tokens.get("cumulative_summarization_estimated") or 0)
    net_saved = int(tokens.get("cumulative_net_saved") or 0)
    final_full = int(tokens.get("final_prompt_full_estimated") or 0)
    final_sent = int(tokens.get("final_prompt_estimated") or 0)
    final_turn_saved = max(0, final_full - final_sent)
    chat_saved = max(0, prompt_full - prompt_sent)

    return {
        "prompt_full_counterfactual": prompt_full,
        "prompt_sent_compressed": prompt_sent,
        "chat_prompt_saved": chat_saved,
        "summarization_cost": summarize,
        "net_saved": net_saved,
        "final_turn_prompt_saved": final_turn_saved,
        "without_cumulative_prompt": int(
            without_tokens.get("cumulative_prompt_estimated") or 0
        ),
        "merge_count": int(with_track.get("merge_count") or 0),
        "script_turns": int(with_track.get("script_turns") or 0),
        "payback": "yes" if net_saved > 0 else "not_yet",
    }


def _pct_saved(before, after):
    before = int(before or 0)
    after = int(after or 0)
    if before <= 0:
        return 0.0
    return round(max(0.0, (before - after) / before * 100), 1)


def build_visual_comparison(comparison):
    without = comparison.get("without_compression") or {}
    with_track = comparison.get("with_compression") or {}
    breakdown = comparison.get("token_breakdown") or {}

    recall_off = build_recall_payload(without)
    recall_on = build_recall_payload(with_track)
    max_tokens = max(
        recall_off["prompt_tokens"],
        recall_on["prompt_tokens_full"],
        recall_on["prompt_tokens"],
        1,
    )

    off_facts = without.get("judge", {}).get("facts") or []
    on_facts = with_track.get("judge", {}).get("facts") or []
    off_ok = sum(1 for item in off_facts if item.get("found"))
    on_ok = sum(1 for item in on_facts if item.get("found"))
    fact_total = len(off_facts) or len(on_facts) or 3

    recall_pct = _pct_saved(recall_off["prompt_tokens"], recall_on["prompt_tokens"])

    return {
        "story": list(COMPARE_STORY),
        "headline_before": recall_off["prompt_tokens"],
        "headline_after": recall_on["prompt_tokens"],
        "headline_reduction_pct": recall_pct,
        "bars": [
            {
                "label": "Без сжатия — в prompt вся история",
                "tokens": recall_off["prompt_tokens"],
                "width_pct": round(recall_off["prompt_tokens"] / max_tokens * 100, 1),
                "tone": "bad",
                "detail": (
                    f"{recall_off['messages_sent']} сообщений · "
                    f"≈{recall_off['prompt_tokens']} tok"
                ),
            },
            {
                "label": "Со сжатием — резюме + хвост",
                "tokens": recall_on["prompt_tokens"],
                "width_pct": round(recall_on["prompt_tokens"] / max_tokens * 100, 1),
                "tone": "good",
                "detail": (
                    f"{recall_on['messages_sent']} сообщ. + "
                    f"{recall_on['summary_chars']} симв. резюме · "
                    f"≈{recall_on['prompt_tokens']} tok"
                ),
            },
        ],
        "table": [
            {
                "label": "Recall prompt (последний запрос)",
                "before": recall_off["prompt_tokens"],
                "after": recall_on["prompt_tokens"],
                "saved_pct": recall_pct,
            },
            {
                "label": "Сообщений в prompt",
                "before": recall_off["messages_sent"],
                "after": recall_on["messages_sent"],
                "saved_pct": _pct_saved(recall_off["messages_sent"], recall_on["messages_sent"]),
            },
            {
                "label": "Факты из 1-го сообщения",
                "before": f"{off_ok}/{fact_total}",
                "after": f"{on_ok}/{fact_total}",
                "saved_pct": None,
            },
            {
                "label": "Весь сценарий (сумма prompt)",
                "before": breakdown.get("without_cumulative_prompt", 0),
                "after": int(breakdown.get("prompt_sent_compressed", 0))
                + int(breakdown.get("summarization_cost", 0)),
                "saved_pct": _pct_saved(
                    breakdown.get("without_cumulative_prompt", 0),
                    int(breakdown.get("prompt_sent_compressed", 0))
                    + int(breakdown.get("summarization_cost", 0)),
                ),
            },
        ],
        "punchline": (
            f"Recall: {recall_off['prompt_tokens']} → {recall_on['prompt_tokens']} tok "
            f"(−{recall_pct}%). Память: {on_ok}/{fact_total} фактов."
        ),
        "net_saved": int(breakdown.get("net_saved") or 0),
        "merge_count": int(breakdown.get("merge_count") or 0),
    }


def build_compare_verdict(comparison):
    visual = comparison.get("visual") or build_visual_comparison(comparison)
    breakdown = comparison.get("token_breakdown") or {}
    quality = comparison.get("quality_delta") or "similar"

    lines = [
        visual.get("punchline", ""),
    ]

    net = int(breakdown.get("net_saved") or 0)
    if net > 0:
        lines.append(
            f"За {breakdown.get('script_turns', '—')} ходов сжатие сэкономило {net} tok "
            f"({breakdown.get('merge_count', 0)} merge)."
        )
    else:
        lines.append(
            f"Merge стоит {breakdown.get('summarization_cost', 0)} tok — "
            f"на коротком диалоге overhead виден, на recall выигрыш {visual.get('headline_reduction_pct', 0)}%."
        )

    quality_notes = {
        "with_scored_higher": "Со сжатием recall точнее.",
        "with_scored_lower": "Со сжатием recall хуже — summary потеряло факты.",
        "similar": "Recall одинаковый.",
        "equivalent_recall": "Все три факта вспомнили — сжатие не ухудшило память.",
    }
    lines.append(quality_notes.get(quality, quality))
    return " ".join(line for line in lines if line)


def format_score(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"
