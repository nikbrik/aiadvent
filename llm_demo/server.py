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

TEMPERATURE_RUNS = [0.0, 0.7, 1.2]
TEMPERATURE_LABELS = {
    0.0: "temperature = 0",
    0.7: "temperature = 0.7",
    1.2: "temperature = 1.2",
}
TEMPERATURE_GUIDANCE = {
    0.0: "Лучше для воспроизводимых ответов, фактов, инструкций и формата.",
    0.7: "Лучше для обычных творческих задач: баланс качества и вариативности.",
    1.2: "Лучше для брейншторма, шуток и поиска необычных вариантов.",
}
DEFAULT_PROVIDER = {
    "allow_fallbacks": False,
    "require_parameters": True,
}
DEFAULT_TASK = (
    "Расскажи короткую комедийную историю о роботе с Claude Mythos на борту. "
    "Ровно 5 предложений. Обязательно придумай: 1 неожиданный предмет, "
    "1 странную профессию робота, 1 абсурдную финальную фразу. Не используй списки."
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


def sampling_options(payload):
    return {
        "model": str(payload.get("model", "")).strip() or None,
        "temperature": parse_float(payload.get("temperature", 0.4), "temperature", 0.0, 2.0),
        "top_p": parse_float(payload.get("top_p", 1.0), "top_p", 0.0, 1.0),
        "top_k": parse_int(payload.get("top_k", 80), "top_k", 0, 100),
        "provider": DEFAULT_PROVIDER,
        "include_reasoning": parse_bool(payload.get("include_reasoning"), default=False),
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
    count = sentence_count(text)
    robot_ok = "робот" in lower
    mythos_ok = "claude" in lower and "mythos" in lower
    no_list_ok = not re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", text)
    five_sentences_ok = count == 5
    score = sum([robot_ok, mythos_ok, no_list_ok, five_sentences_ok])
    notes = []

    notes.append("робот найден" if robot_ok else "робот не найден")
    notes.append("Claude Mythos найден" if mythos_ok else "Claude Mythos не найден")
    notes.append("без списка" if no_list_ok else "похож на список")
    notes.append(f"{count} предложений")

    return {
        "score": score,
        "max_score": 4,
        "robot_ok": robot_ok,
        "mythos_ok": mythos_ok,
        "no_list_ok": no_list_ok,
        "five_sentences_ok": five_sentences_ok,
        "sentence_count": count,
        "notes": notes,
    }


def word_set(text):
    return set(re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", str(text or "").lower()))


def diversity_score(text, other_texts):
    current = word_set(text)
    if not current or not other_texts:
        return None

    distances = []
    for other in other_texts:
        other_words = word_set(other)
        if not other_words:
            continue
        overlap = current & other_words
        union = current | other_words
        distances.append(1 - (len(overlap) / len(union)))

    if not distances:
        return None

    return round(sum(distances) / len(distances), 3)


def attach_diversity(results):
    successful = [result for result in results if not result.get("error")]
    for result in successful:
        others = [
            other.get("content") or ""
            for other in successful
            if other is not result
        ]
        result["diversity_score"] = diversity_score(result.get("content"), others)
    return results


def creativity_note(temperature):
    if temperature == 0.0:
        return "Низкая случайность: стиль обычно ровнее и предсказуемее."
    if temperature == 0.7:
        return "Средняя случайность: больше живости без резкого распада структуры."
    return (
        "Высокая случайность: больше неожиданных ходов, но выше риск лишней длины "
        "и странных формулировок."
    )


def format_temperature(value):
    if value == 0.0:
        return "0"
    return str(value)


def attach_result_metadata(result, temperature):
    content = str(result.get("content") or "").strip()
    result["content"] = content
    result["temperature"] = temperature
    result["label"] = TEMPERATURE_LABELS.get(temperature, f"temperature = {format_temperature(temperature)}")
    result["character_count"] = len(content)
    result["sentence_count"] = sentence_count(content)
    result["evaluation"] = prompt_adherence(content)
    result["creativity_note"] = creativity_note(temperature)
    result["recommended_for"] = TEMPERATURE_GUIDANCE.get(
        temperature,
        "Используйте как промежуточную настройку между стабильностью и вариативностью.",
    )
    return result


def run_completion(payload, temperature=None):
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")

    options = sampling_options(payload)
    if temperature is not None:
        options["temperature"] = temperature

    completion = call_model([{"role": "user", "content": prompt}], options)
    return attach_result_metadata(completion, options["temperature"])


def comparison_summary(results):
    successful = [result for result in results if not result.get("error")]
    if not successful:
        return "Все запросы завершились ошибкой. Сравнение недоступно."

    best_accuracy = max(result["evaluation"]["score"] for result in successful)
    accurate = [
        result["label"] for result in successful
        if result["evaluation"]["score"] == best_accuracy
    ]
    diverse = [
        result for result in successful
        if result.get("diversity_score") is not None
    ]
    most_diverse = max(diverse, key=lambda item: item["diversity_score"]) if diverse else None

    summary = f"Самая точная настройка по проверке prompt: {', '.join(accurate)}."
    if most_diverse and most_diverse["diversity_score"] > 0:
        summary += (
            f" Самый отличающийся ответ: {most_diverse['label']} "
            f"(diversity {most_diverse['diversity_score']})."
        )
    elif most_diverse:
        summary += " Ответы почти не отличаются по словарю."
    summary += " Для вывода: 0 — стабильность, 0.7 — баланс, 1.2 — идеи и вариативность."
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

        results = []

        for temperature in TEMPERATURE_RUNS:
            try:
                completion = run_completion(payload, temperature)
                results.append(completion)
            except OpenRouterError as exc:
                results.append({
                    "temperature": temperature,
                    "label": TEMPERATURE_LABELS[temperature],
                    "error": str(exc),
                    "status": exc.status,
                    "evaluation": prompt_adherence(""),
                })
    except ValueError as exc:
        return error_response(str(exc), 400)

    attach_diversity(results)

    return jsonify({
        "task": str(payload.get("prompt", "")).strip(),
        "temperatures": TEMPERATURE_RUNS,
        "results": results,
        "summary": comparison_summary(results),
    })


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
