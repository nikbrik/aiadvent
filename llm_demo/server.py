import json
import logging
import os
import re

from flask import Flask, jsonify, request, send_from_directory

from http_log import log_exchange
from llm_client import OpenRouterError, chat_completion


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger("llm_demo")

app = Flask(__name__, static_folder="static", static_url_path="/static")

REASONING_EXCLUDED = {"exclude": True}

MODEL_RUNS = [
    {
        "tier": "weak",
        "label": "Weak · Qwen3 8B",
        "model": "qwen/qwen3-8b",
        "lab": "Alibaba Qwen",
        "scale": "8.2B dense",
        "parameters": "8.2B",
        "active_parameters": "8.2B",
        "architecture": "dense",
        "context_window": "131K",
        "release": "2025-04-28",
        "pricing": {"input": 0.05, "output": 0.40},
        "reasoning": REASONING_EXCLUDED,
        "links": {
            "openrouter": "https://openrouter.ai/qwen/qwen3-8b",
            "hf": "https://huggingface.co/Qwen/Qwen3-8B",
        },
        "recommended_for": "Малый baseline: простые черновики и дешевые ответы с повышенным риском ошибок.",
    },
    {
        "tier": "medium",
        "label": "Medium · Z.ai GLM 4.7 Flash",
        "model": "z-ai/glm-4.7-flash",
        "lab": "Z.ai / Zhipu",
        "scale": "30B-class MoE",
        "parameters": "30B-class",
        "active_parameters": "MoE active set not specified",
        "architecture": "MoE",
        "context_window": "203K",
        "release": "2026-01-19",
        "pricing": {"input": 0.06, "output": 0.40},
        "reasoning": REASONING_EXCLUDED,
        "links": {
            "openrouter": "https://openrouter.ai/z-ai/glm-4.7-flash",
            "hf": "https://huggingface.co/zai-org/GLM-4.7-Flash",
        },
        "recommended_for": "Средний класс: заметно больше reasoning/agentic capacity при still-low цене.",
    },
    {
        "tier": "strong",
        "label": "Strong · DeepSeek V4 Pro",
        "model": "deepseek/deepseek-v4-pro",
        "lab": "DeepSeek",
        "scale": "1.6T total / 49B active",
        "parameters": "1.6T total",
        "active_parameters": "49B active",
        "architecture": "MoE",
        "context_window": "1M",
        "release": "2026-04-24",
        "pricing": {"input": 0.435, "output": 0.87},
        "reasoning": REASONING_EXCLUDED,
        "links": {
            "openrouter": "https://openrouter.ai/deepseek/deepseek-v4-pro",
            "hf": "https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro",
        },
        "recommended_for": "Сложный reasoning, длинный контекст, кодовая база целиком и финальная проверка.",
    },
]
MODEL_BY_ID = {item["model"]: item for item in MODEL_RUNS}
DEFAULT_MODEL_ID = MODEL_RUNS[0]["model"]
DEFAULT_PROVIDER = {
    "allow_fallbacks": False,
}
DEFAULT_TASK = (
    "Ты CTO интернет-магазина и выбираешь LLM для трех задач: "
    "1) быстрые FAQ-ответы клиентам, где важны скорость и низкая цена; "
    "2) анализ 40-страничного договора поставки, где важны качество и длинный контекст; "
    "3) поиск ошибки в SQL-запросе, где важны точность и объяснение риска. "
    "Составь markdown-таблицу с колонками: Задача, Выбор модели (weak/medium/strong), Почему, Риск. "
    "После таблицы добавь короткий вывод из 2 предложений. "
    "Обязательно сравни качество, скорость, стоимость и ресурсоемкость. "
    "Не выдумывай внешние факты."
)


def incoming_body():
    if request.method not in ("POST", "PUT", "PATCH") or not request.content_length:
        return None
    if request.is_json:
        return request.get_json(silent=True)
    if request.data:
        return request.data.decode("utf-8", errors="replace")
    return None


@app.before_request
def log_incoming_request():
    log_exchange(
        logger,
        theme="browser_in",
        title="← IN  Browser → Flask",
        method=request.method,
        url=request.full_path.rstrip("?"),
        request_headers=request.headers,
        body=incoming_body(),
        skip_body=request.path.startswith("/static"),
    )


def outgoing_body(response):
    if response.direct_passthrough:
        length = response.content_length
        if length is None:
            length = response.headers.get("Content-Length", "?")
        return f"({length} bytes, {response.content_type or 'no content-type'})"

    if response.content_type and "json" in response.content_type:
        try:
            return json.loads(response.get_data(as_text=True))
        except (json.JSONDecodeError, TypeError, ValueError):
            return response.get_data(as_text=True)

    data = response.get_data()
    return f"({len(data)} bytes, {response.content_type or 'no content-type'})"


@app.after_request
def log_outgoing_response(response):
    is_static = request.path.startswith("/static")
    body = None if is_static else outgoing_body(response)

    log_exchange(
        logger,
        theme="browser_out",
        title="→ OUT Flask → Browser",
        method=request.method,
        url=request.path,
        status=response.status_code,
        response_headers=response.headers,
        body=body,
        skip_body=is_static,
    )
    return response


def sampling_options(payload):
    return {
        "model": str(payload.get("model", "")).strip() or DEFAULT_MODEL_ID,
        "provider": DEFAULT_PROVIDER,
        "include_reasoning": False,
        "reasoning": REASONING_EXCLUDED,
    }


def call_model(messages, options):
    return chat_completion(messages=messages, **options)


def sentence_count(text):
    sentences = [
        item for item in re.split(r"[.!?…]+(?:\s+|$)", str(text or "").strip())
        if item.strip()
    ]
    return len(sentences)


def prompt_adherence(content):
    text = str(content or "")
    lower = text.lower()
    table_ok = "|" in text and "задача" in lower and "риск" in lower
    task_ok = all(marker in lower for marker in ("faq", "договор", "sql"))
    tier_ok = all(marker in lower for marker in ("weak", "medium", "strong"))
    quality_ok = "качеств" in lower or "точн" in lower
    speed_ok = "скорост" in lower or "быстр" in lower
    cost_ok = any(
        marker in lower
        for marker in ("стоим", "стоит", "цен", "денег", "дешев", "дорог", "бесплат")
    )
    resource_ok = "ресурсо" in lower or "ресурс" in lower or "контекст" in lower or "вычисл" in lower
    conclusion_ok = "вывод" in lower
    external_model_markers = (
        "gpt",
        "claude",
        "gemini",
        "llama",
        "mistral",
        "gemma",
        "sonnet",
        "opus",
        "haiku",
    )
    no_external_models_ok = not any(marker in lower for marker in external_model_markers)
    score = sum([
        table_ok,
        task_ok,
        tier_ok,
        quality_ok,
        speed_ok,
        cost_ok,
        resource_ok,
        conclusion_ok,
        no_external_models_ok,
    ])
    notes = []

    notes.append("таблица есть" if table_ok else "таблица/риск не найдены")
    notes.append("3 задачи найдены" if task_ok else "не все задачи найдены")
    notes.append("weak/medium/strong есть" if tier_ok else "не все tier найдены")
    notes.append("качество найдено" if quality_ok else "качество не найдено")
    notes.append("скорость найдена" if speed_ok else "скорость не найдена")
    notes.append("стоимость найдена" if cost_ok else "стоимость не найдена")
    notes.append("ресурсоемкость найдена" if resource_ok else "ресурсоемкость не найдена")
    notes.append("вывод найден" if conclusion_ok else "вывод не найден")
    notes.append(
        "без внешних model facts"
        if no_external_models_ok
        else "есть внешние model facts"
    )

    return {
        "score": score,
        "max_score": 9,
        "table_ok": table_ok,
        "task_ok": task_ok,
        "tier_ok": tier_ok,
        "quality_ok": quality_ok,
        "speed_ok": speed_ok,
        "cost_ok": cost_ok,
        "resource_ok": resource_ok,
        "conclusion_ok": conclusion_ok,
        "no_external_models_ok": no_external_models_ok,
        "sentence_count": sentence_count(text),
        "notes": notes,
    }


def model_metadata(model_id):
    if model_id in MODEL_BY_ID:
        return MODEL_BY_ID[model_id]

    return {
        "tier": "custom",
        "label": model_id,
        "model": model_id,
        "lab": "custom",
        "scale": "unknown",
        "parameters": "unknown",
        "active_parameters": "unknown",
        "architecture": "unknown",
        "context_window": "unknown",
        "release": "unknown",
        "pricing": {"input": None, "output": None},
        "reasoning": REASONING_EXCLUDED,
        "links": {},
        "recommended_for": "Пользовательская модель вне Day 5 набора.",
    }


def to_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_cost(result, metadata):
    cost = to_number(result.get("cost"))
    if cost is not None:
        return cost, False

    prompt_tokens = result.get("prompt_tokens")
    completion_tokens = result.get("completion_tokens")
    input_price = metadata["pricing"].get("input")
    output_price = metadata["pricing"].get("output")

    if (
        prompt_tokens is None
        or completion_tokens is None
        or input_price is None
        or output_price is None
    ):
        return None, False

    estimated = (prompt_tokens / 1_000_000 * input_price) + (
        completion_tokens / 1_000_000 * output_price
    )
    return round(estimated, 8), True


def attach_result_metadata(result, metadata):
    content = str(result.get("content") or "").strip()
    cost, cost_estimated = estimate_cost(result, metadata)

    result["content"] = content
    result["tier"] = metadata["tier"]
    result["label"] = metadata["label"]
    result["requested_model"] = metadata["model"]
    result["model"] = result.get("model") or metadata["model"]
    result["lab"] = metadata["lab"]
    result["scale"] = metadata["scale"]
    result["parameters"] = metadata["parameters"]
    result["active_parameters"] = metadata["active_parameters"]
    result["architecture"] = metadata["architecture"]
    result["context_window"] = metadata["context_window"]
    result["release"] = metadata["release"]
    result["pricing"] = metadata["pricing"]
    result["reasoning_policy"] = metadata["reasoning"]
    result["links"] = metadata["links"]
    result["recommended_for"] = metadata["recommended_for"]
    result["cost"] = cost
    result["cost_estimated"] = cost_estimated
    result["character_count"] = len(content)
    result["sentence_count"] = sentence_count(content)
    result["evaluation"] = prompt_adherence(content)
    result["quality_note"] = (
        "Эвристика проверяет соблюдение prompt, а не заменяет человеческую оценку ответа."
    )
    return result


def error_result(metadata, exc):
    return {
        "tier": metadata["tier"],
        "label": metadata["label"],
        "requested_model": metadata["model"],
        "model": metadata["model"],
        "lab": metadata["lab"],
        "scale": metadata["scale"],
        "parameters": metadata["parameters"],
        "active_parameters": metadata["active_parameters"],
        "architecture": metadata["architecture"],
        "context_window": metadata["context_window"],
        "release": metadata["release"],
        "pricing": metadata["pricing"],
        "reasoning_policy": metadata["reasoning"],
        "links": metadata["links"],
        "recommended_for": metadata["recommended_for"],
        "content": "",
        "error": str(exc),
        "status": exc.status,
        "cost": None,
        "cost_estimated": False,
        "evaluation": prompt_adherence(""),
    }


def run_completion(payload, metadata=None):
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")

    options = sampling_options(payload)
    if metadata is None:
        metadata = model_metadata(options["model"])
    else:
        options["model"] = metadata["model"]
    options["reasoning"] = metadata["reasoning"]
    options["include_reasoning"] = False

    completion = call_model([{"role": "user", "content": prompt}], options)
    return attach_result_metadata(completion, metadata)


def format_ms(value):
    if value is None:
        return "n/a"
    return f"{round(value)} ms"


def format_cost(value):
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def comparison_summary(results):
    successful = [result for result in results if not result.get("error")]
    if not successful:
        return "Все запросы завершились ошибкой. Сравнение недоступно."

    best_quality = max(result["evaluation"]["score"] for result in successful)
    max_quality = max(result["evaluation"]["max_score"] for result in successful)
    quality_winners = [
        result["label"] for result in successful
        if result["evaluation"]["score"] == best_quality
    ]

    timed = [result for result in successful if result.get("duration_ms") is not None]
    fastest = min(timed, key=lambda item: item["duration_ms"]) if timed else None

    priced = [result for result in successful if result.get("cost") is not None]
    cheapest = min(priced, key=lambda item: item["cost"]) if priced else None

    tokenized = [result for result in successful if result.get("total_tokens") is not None]
    lightest = min(tokenized, key=lambda item: item["total_tokens"]) if tokenized else None

    summary = (
        f"Лучшее качество по эвристике prompt: {', '.join(quality_winners)} "
        f"({best_quality}/{max_quality})."
    )
    if fastest:
        summary += f" Самый быстрый ответ: {fastest['label']} ({format_ms(fastest['duration_ms'])})."
    if cheapest:
        suffix = ", estimate" if cheapest.get("cost_estimated") else ""
        summary += f" Самый дешевый запуск: {cheapest['label']} ({format_cost(cheapest['cost'])}{suffix})."
    if lightest:
        summary += f" Меньше всего tokens: {lightest['label']} ({lightest['total_tokens']})."
    summary += " Короткий вывод делайте по трем осям: качество, скорость, ресурсоемкость."
    return summary


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}

    try:
        completion = run_completion(payload)
    except ValueError as exc:
        return error_response(str(exc), 400)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)

    return jsonify(completion)


@app.post("/api/compare")
def compare():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}

    try:
        if not str(payload.get("prompt", "")).strip():
            raise ValueError("prompt is required")

        compare_payload = {"prompt": payload.get("prompt", "")}
        results = []

        for metadata in MODEL_RUNS:
            try:
                results.append(run_completion(compare_payload, metadata))
            except OpenRouterError as exc:
                results.append(error_result(metadata, exc))
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify({
        "task": str(payload.get("prompt", "")).strip(),
        "models": MODEL_RUNS,
        "generation": {
            "usage": {"include": True},
            "provider": DEFAULT_PROVIDER,
            "reasoning_by_model": {
                metadata["model"]: metadata["reasoning"]
                for metadata in MODEL_RUNS
            },
        },
        "results": results,
        "summary": comparison_summary(results),
    })


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
