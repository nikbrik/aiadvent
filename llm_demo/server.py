import os

from flask import Flask, jsonify, request, send_from_directory

from llm_client import OpenRouterError, chat_completion


app = Flask(__name__, static_folder="static", static_url_path="/static")


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
