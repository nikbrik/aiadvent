import json
import logging
import os

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

CONTROL_MODES = {"none", "api", "system"}
API_RESPONSE_FORMAT = {"type": "json_object"}
DEFAULT_SYSTEM_MESSAGE = """Ты отвечаешь строго по правилам:
1. Формат: нумерованный список из ровно 5 пунктов (1. … 2. … и т.д.).
2. Длина: каждый пункт — не более 15 слов.
3. Завершение: после пункта 5 сразу остановись. Не добавляй вступление, заключение и текст после списка."""


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


def parse_control_mode(value):
    mode = str(value or "none").strip().lower()
    if mode not in CONTROL_MODES:
        raise ValueError("control_mode must be one of: none, api, system")
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


def parse_response_format(value):
    if value in (None, ""):
        return API_RESPONSE_FORMAT

    if not isinstance(value, dict):
        raise ValueError("response_format must be an object")

    if value != API_RESPONSE_FORMAT:
        raise ValueError('response_format must be {"type": "json_object"}')

    return value


def build_messages(control_mode, prompt, system_message):
    if control_mode != "system":
        return [{"role": "user", "content": prompt}]

    message = str(system_message or "").strip()
    if not message:
        raise ValueError("system_message is required for system control mode")

    return [
        {"role": "system", "content": message},
        {"role": "user", "content": prompt},
    ]


def build_api_options(payload, control_mode):
    if control_mode == "api":
        return {
            "max_tokens": parse_int(payload.get("max_tokens", 120), "max_tokens", 1, 4096),
            "stop": parse_stop_sequences(payload.get("stop")),
            "response_format": parse_response_format(payload.get("response_format")),
            "provider": {
                "order": ["novita"],
                "allow_fallbacks": False,
                "require_parameters": True,
            },
        }

    return {}


def run_completion(payload, control_mode):
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")

    model = str(payload.get("model", "")).strip() or None
    temperature = parse_float(payload.get("temperature", 0.7), "temperature", 0.0, 2.0)
    top_p = parse_float(payload.get("top_p", 1.0), "top_p", 0.0, 1.0)
    top_k = parse_int(payload.get("top_k", 40), "top_k", 0, 100)
    messages = build_messages(control_mode, prompt, payload.get("system_message", DEFAULT_SYSTEM_MESSAGE))

    return chat_completion(
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        model=model,
        **build_api_options(payload, control_mode),
    )


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}

    try:
        control_mode = parse_control_mode(payload.get("control_mode", "none"))
        completion = run_completion(payload, control_mode)
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

        modes = [
            ("none", "Без ограничений"),
            ("api", "API control"),
            ("system", "System control"),
        ]
        results = []

        for mode, label in modes:
            try:
                completion = run_completion(payload, mode)
                completion.update({"control_mode": mode, "label": label})
                results.append(completion)
            except OpenRouterError as exc:
                results.append({
                    "control_mode": mode,
                    "label": label,
                    "error": str(exc),
                    "status": exc.status,
                })
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify({"results": results})


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
