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


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()

    if not prompt:
        return error_response("prompt is required", 400)

    try:
        model = str(payload.get("model", "")).strip() or None
        temperature = parse_float(payload.get("temperature", 0.7), "temperature", 0.0, 2.0)
        top_p = parse_float(payload.get("top_p", 1.0), "top_p", 0.0, 1.0)
        top_k = parse_int(payload.get("top_k", 40), "top_k", 0, 100)
        content = chat_completion(
            prompt=prompt,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            model=model,
        )
    except ValueError as exc:
        return error_response(str(exc), 400)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)

    return jsonify({"content": content})


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
