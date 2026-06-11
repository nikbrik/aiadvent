import json
import logging
import os
import uuid

from flask import Flask, g, jsonify, request, send_from_directory

from agent import ChatAgent, FileMemoryStore
from http_log import log_exchange
from llm_client import OpenRouterError, chat_completion


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger("llm_demo")

app = Flask(__name__, static_folder="static", static_url_path="/static")
agent = ChatAgent(
    memory_store=FileMemoryStore(os.path.join(os.path.dirname(__file__), "data", "clients")),
    llm=chat_completion,
)


def incoming_body():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE") or not request.content_length:
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


@app.before_request
def ensure_client_id():
    if not request.path.startswith("/api/"):
        return

    raw_client_id = request.cookies.get("client_id", "")
    try:
        client_id = str(uuid.UUID(raw_client_id))
        g.set_client_cookie = False
    except (TypeError, ValueError):
        client_id = str(uuid.uuid4())
        g.set_client_cookie = True
    g.client_id = client_id


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
    if getattr(g, "set_client_cookie", False):
        response.set_cookie(
            "client_id",
            g.client_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="Lax",
        )

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


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/chat")
def chat_state():
    return jsonify(agent.snapshot(g.client_id))


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}
    try:
        result = agent.respond(g.client_id, payload.get("message", ""))
    except ValueError as exc:
        return error_response(str(exc), 400)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)

    if result.get("overflow"):
        return jsonify(result), 413
    return jsonify(result)


@app.delete("/api/chat")
def clear_chat():
    return jsonify(agent.clear(g.client_id))


@app.post("/api/demo/short")
def demo_short():
    try:
        result = agent.run_demo_short(g.client_id)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)
    return jsonify(result)


@app.post("/api/demo/long")
def demo_long():
    try:
        result = agent.run_demo_long(g.client_id)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)
    return jsonify(result)


@app.post("/api/demo/overflow")
def demo_overflow():
    result = agent.run_demo_overflow(g.client_id)
    return jsonify(result), 413


@app.post("/api/demo/provider-overflow")
def demo_provider_overflow():
    try:
        result = agent.run_demo_provider_overflow(g.client_id)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)

    if result.get("provider_error"):
        status = int(result["provider_error"].get("http_status") or 502)
        return jsonify(result), status
    return jsonify(result)


@app.post("/api/demo/memory-loss")
def demo_memory_loss():
    try:
        result = agent.run_demo_memory_loss(g.client_id)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)

    if result.get("memory_loss", {}).get("provider_error") or (
        result.get("last_turn", {}).get("status") == "provider_error"
        and result.get("last_turn", {}).get("demo") == "memory_loss"
    ):
        status = int(
            (result.get("provider_error") or result.get("last_turn", {}).get("provider_error") or {}).get(
                "http_status"
            )
            or 502
        )
        return jsonify(result), status
    return jsonify(result)


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, threaded=True)
