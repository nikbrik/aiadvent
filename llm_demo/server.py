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

REASONING_MODES = {"direct", "step", "prompt_chain", "experts"}
MODE_LABELS = {
    "direct": "Прямой ответ",
    "step": "System: решай пошагово",
    "prompt_chain": "System: prompt → решение",
    "experts": "System: группа экспертов",
}
TASK_SOURCE_URL = "https://cpm-pert.com/example-pert-cpm"
REFERENCE_DURATION = 44
REFERENCE_PATH = "A → B → C → E → F → J → L → N"
REFERENCE_PATH_COMPACT = "ABCEFJLN"
DEMO_TASK = """PERT/CPM задача: строительный проект из 14 активностей.

Даны активности, длительности в днях и непосредственные предшественники:

A Excavation — 2 — нет
B Foundation — 4 — A
C Walls — 10 — B
D Roof — 6 — C
E Exterior enclosure — 4 — C
F Interior enclosure — 5 — E
G Exterior walls — 7 — D
H Exterior painting — 9 — E, G
I Electrical — 7 — C
J Partitions — 8 — F, I
K Flooring — 4 — J
L Interior painting — 5 — J
M Exterior finishing — 2 — H
N Interior finishing — 6 — K, L

Найдите минимальную длительность проекта и критический путь."""
REFERENCE_ANSWER = f"Минимальная длительность: {REFERENCE_DURATION} дня. Критический путь: {REFERENCE_PATH}."
STEP_SYSTEM_PROMPT = """Решай пошагово.
Верни ответ в двух блоках:

ХОД РАССУЖДЕНИЯ:
- сделай forward pass: ES/EF для важных веток;
- сделай backward/slack check для критического пути;
- проверь конкурирующие конечные ветки M и N.

ИТОГ:
- минимальная длительность проекта;
- критический путь."""
PROMPT_WRITER_SYSTEM_PROMPT = """Ты prompt engineer.
На основе задачи пользователя составь один сильный промпт для модели-решателя.
Промпт должен заставить модель:
- разобрать зависимости;
- рассчитать ES/EF через forward pass;
- проверить LS/LF/slack через backward pass;
- проверить критический путь;
- сравнить конечные ветки;
- вернуть два блока: ХОД РАССУЖДЕНИЯ и ИТОГ.
Не решай задачу. Верни только готовый промпт на русском."""
PROMPT_CHAIN_SOLVER_SYSTEM_PROMPT = """Ты решаешь задачу по промпту пользователя.
Следуй промпту буквально, проверь арифметику и в конце явно укажи ответ."""
EXPERTS_SYSTEM_PROMPT = """Создай группу экспертов и получи решение от каждого:
1. Аналитик делает forward pass и находит длительность.
2. Инженер делает backward/slack check.
3. Критик проверяет арифметику и конкурирующие конечные ветки.

Верни ответ в двух блоках:

ХОД РАССУЖДЕНИЯ:
- краткое решение каждого эксперта;
- исправления критика, если есть.

ИТОГ:
- минимальная длительность проекта;
- критический путь."""


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


def parse_float(value, name, min_value, max_value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")

    if number < min_value or number > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")

    return number


def parse_int(value, name, min_value, max_value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")

    if number < min_value or number > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")

    return number


def parse_bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return bool(value)


def parse_reasoning_mode(value):
    mode = str(value or "direct").strip().lower()
    if mode not in REASONING_MODES:
        raise ValueError("reasoning_mode must be one of: direct, step, prompt_chain, experts")
    return mode


def decode_stop_sequence(value):
    return (
        value.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
    )


def parse_stop_sequences(value):
    if value is None:
        return []

    if isinstance(value, str):
        raw_items = []
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            raw_items.extend(line.split(","))
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError("stop must be a string or an array of strings")

    stop = []
    for item in raw_items:
        if not isinstance(item, str):
            raise ValueError("stop must contain only strings")

        sequence = decode_stop_sequence(item.strip())
        if sequence:
            stop.append(sequence)

    return stop


def build_messages(reasoning_mode, prompt):
    if reasoning_mode == "direct":
        return [{"role": "user", "content": prompt}]

    system_prompts = {
        "step": STEP_SYSTEM_PROMPT,
        "experts": EXPERTS_SYSTEM_PROMPT,
    }

    return [
        {"role": "system", "content": system_prompts[reasoning_mode]},
        {"role": "user", "content": prompt},
    ]


def sampling_options(payload):
    return {
        "model": str(payload.get("model", "")).strip() or None,
        "temperature": parse_float(payload.get("temperature", 0.4), "temperature", 0.0, 2.0),
        "top_p": parse_float(payload.get("top_p", 1.0), "top_p", 0.0, 1.0),
        "top_k": parse_int(payload.get("top_k", 40), "top_k", 0, 100),
        "include_reasoning": parse_bool(payload.get("include_reasoning"), default=True),
    }


def call_model(messages, options):
    return chat_completion(messages=messages, **options)


def run_prompt_chain(prompt, options):
    prompt_completion = call_model(
        [
            {"role": "system", "content": PROMPT_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        options,
    )
    generated_prompt = str(prompt_completion.get("content") or "").strip()
    if not generated_prompt:
        raise OpenRouterError("Prompt writer returned empty content", 502)

    answer_completion = call_model(
        [
            {"role": "system", "content": PROMPT_CHAIN_SOLVER_SYSTEM_PROMPT},
            {"role": "user", "content": generated_prompt},
        ],
        options,
    )
    answer_completion["generated_prompt"] = generated_prompt
    answer_completion["prompt_finish_reason"] = prompt_completion.get("finish_reason")
    answer_completion["prompt_completion_tokens"] = prompt_completion.get("completion_tokens")

    prompt_tokens = prompt_completion.get("completion_tokens")
    answer_tokens = answer_completion.get("completion_tokens")
    if prompt_tokens is not None and answer_tokens is not None:
        answer_completion["completion_tokens_total"] = prompt_tokens + answer_tokens

    return answer_completion


def evaluate_answer(content):
    text = str(content or "")
    upper = text.upper()
    compact = re.sub(r"[^A-Z0-9]+", "", upper)
    duration_ok = bool(re.search(rf"(?<!\d){REFERENCE_DURATION}(?!\d)", text))
    path_ok = REFERENCE_PATH_COMPACT in compact
    score = int(duration_ok) + int(path_ok)
    notes = []

    if duration_ok:
        notes.append(f"{REFERENCE_DURATION} дня найдено")
    else:
        notes.append(f"{REFERENCE_DURATION} дня не найдено")

    if path_ok:
        notes.append(f"путь {REFERENCE_PATH_COMPACT} найден")
    else:
        notes.append(f"путь {REFERENCE_PATH_COMPACT} не найден")

    return {
        "score": score,
        "max_score": 2,
        "duration_ok": duration_ok,
        "path_ok": path_ok,
        "notes": notes,
    }


def split_visible_sections(content, reasoning_mode):
    text = str(content or "").strip()
    if not text:
        return {
            "visible_reasoning": "Модель не вернула видимый текст.",
            "final_answer": "",
            "reasoning_source": "empty",
        }

    marker = re.search(r"(?im)^\s*(итог|финальный ответ|ответ)\s*:?\s*$", text)
    if marker:
        before = text[:marker.start()].strip()
        after = text[marker.end():].strip()
        before = re.sub(r"(?im)^\s*ход рассуждения\s*:?\s*", "", before).strip()
        return {
            "visible_reasoning": before or "Отдельный ход рассуждения не найден.",
            "final_answer": after or text,
            "reasoning_source": "visible_output",
        }

    if reasoning_mode == "direct":
        return {
            "visible_reasoning": (
                "Direct baseline: отдельный ход рассуждения не запрошен. "
                "Если OpenRouter не вернул native reasoning, здесь остается только финальный текст модели."
            ),
            "final_answer": text,
            "reasoning_source": "not_requested",
        }

    return {
        "visible_reasoning": text,
        "final_answer": text,
        "reasoning_source": "visible_output",
    }


def attach_result_metadata(result, reasoning_mode):
    native_reasoning = str(result.get("reasoning") or "").strip()
    sections = split_visible_sections(result.get("content"), reasoning_mode)
    if native_reasoning:
        sections["visible_reasoning"] = native_reasoning
        sections["reasoning_source"] = "openrouter_reasoning"

    result["reasoning_mode"] = reasoning_mode
    result["label"] = MODE_LABELS[reasoning_mode]
    result["character_count"] = len(str(result.get("content") or ""))
    result["visible_reasoning"] = sections["visible_reasoning"]
    result["final_answer"] = sections["final_answer"]
    result["reasoning_source"] = sections["reasoning_source"]
    result["evaluation"] = evaluate_answer(result.get("content"))
    return result


def comparison_summary(results):
    scored = [
        result for result in results
        if not result.get("error") and result.get("evaluation")
    ]
    if not scored:
        return "Все запросы завершились ошибкой. Сравнение точности недоступно."

    best_score = max(result["evaluation"]["score"] for result in scored)
    best = [
        result["label"] for result in scored
        if result["evaluation"]["score"] == best_score
    ]
    exact = [
        result["label"] for result in scored
        if result["evaluation"]["score"] == result["evaluation"]["max_score"]
    ]
    best_text = ", ".join(best)

    if exact:
        return (
            f"Эталон: {REFERENCE_ANSWER} "
            f"Наиболее точные по авто-проверке: {', '.join(exact)}."
        )

    return (
        f"Эталон: {REFERENCE_ANSWER} "
        f"Лучший частичный результат: {best_text} ({best_score}/2)."
    )


def run_completion(payload, reasoning_mode):
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")

    options = sampling_options(payload)

    if reasoning_mode == "prompt_chain":
        completion = run_prompt_chain(prompt, options)
    else:
        completion = call_model(build_messages(reasoning_mode, prompt), options)

    return attach_result_metadata(completion, reasoning_mode)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}

    try:
        reasoning_mode = parse_reasoning_mode(payload.get("reasoning_mode", "direct"))
        completion = run_completion(payload, reasoning_mode)
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

        modes = ["direct", "step", "prompt_chain", "experts"]
        results = []

        for mode in modes:
            try:
                completion = run_completion(payload, mode)
                results.append(completion)
            except OpenRouterError as exc:
                results.append({
                    "reasoning_mode": mode,
                    "label": MODE_LABELS[mode],
                    "error": str(exc),
                    "status": exc.status,
                    "evaluation": evaluate_answer(""),
                })
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify({
        "task": str(payload.get("prompt", "")).strip(),
        "task_source_url": TASK_SOURCE_URL,
        "reference_answer": REFERENCE_ANSWER,
        "results": results,
        "summary": comparison_summary(results),
    })


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
