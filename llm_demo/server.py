import json
import logging
import os
import uuid

from flask import Flask, g, jsonify, request, send_from_directory

from agent import ChatAgent, FileMemoryStore, STRATEGY_IDS, comparison_result_for
from demo_script import (
    DEMO_BRANCH_CREATE_STEP,
    DEMO_BRANCH_SWITCHES,
    DEMO_MESSAGES,
    DEMO_TIMELINE,
    DEMO_TOTAL,
)
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
    return jsonify(with_demo_metadata(agent.snapshot(g.client_id)))


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

    return jsonify(with_demo_metadata(result))


@app.post("/api/chat/new")
def new_chat():
    return jsonify(with_demo_metadata(agent.start_new_chat(g.client_id)))


@app.post("/api/chat/resume")
def resume_chat():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}
    try:
        result = agent.resume_chat(g.client_id, payload.get("chat_id", ""))
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify(with_demo_metadata(result))


@app.post("/api/context/strategy")
def set_context_strategy():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}
    try:
        result = agent.set_strategy(g.client_id, payload.get("strategy", ""))
    except ValueError as exc:
        return error_response(str(exc), 400)
    return jsonify(with_demo_metadata(result))


@app.post("/api/context/checkpoint")
def context_checkpoint():
    return jsonify(with_demo_metadata(agent.create_checkpoint(g.client_id)))


@app.post("/api/context/branches")
def context_branches():
    return jsonify(with_demo_metadata(agent.create_branches(g.client_id)))


@app.post("/api/context/branch")
def context_branch():
    if not request.is_json:
        return error_response("Request body must be application/json", 400)

    payload = request.get_json(silent=True) or {}
    try:
        result = agent.switch_branch(g.client_id, payload.get("branch_id", ""))
    except ValueError as exc:
        return error_response(str(exc), 400)
    return jsonify(with_demo_metadata(result))


@app.delete("/api/chat")
def clear_chat():
    return jsonify(with_demo_metadata(agent.clear(g.client_id)))


@app.post("/api/demo/reset")
def demo_reset():
    return jsonify(with_demo_metadata(agent.reset_demo(g.client_id), complete=False))


@app.post("/api/demo/next")
def demo_next():
    state = agent.snapshot(g.client_id)
    progress = min(int(state.get("demo_progress", 0)), DEMO_TOTAL)
    if progress >= DEMO_TOTAL:
        return jsonify(with_demo_metadata(state, complete=True))

    try:
        result = run_demo_step(progress)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify(with_demo_metadata(result))


@app.post("/api/demo/run-active")
def demo_run_active():
    state = agent.snapshot(g.client_id)
    active_strategy = state.get("active_strategy")
    try:
        agent.reset_strategy(g.client_id, active_strategy)
        agent.set_demo_progress(g.client_id, 0)
        result = None
        for progress in range(DEMO_TOTAL):
            result = run_demo_step(progress)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify(with_demo_metadata(result or agent.snapshot(g.client_id), complete=True))


@app.post("/api/demo/run-all")
def demo_run_all():
    results = []
    try:
        agent.reset_demo(g.client_id)
        for strategy_id in STRATEGY_IDS:
            agent.set_strategy(g.client_id, strategy_id)
            agent.reset_strategy(g.client_id, strategy_id)
            agent.set_demo_progress(g.client_id, 0)
            for progress in range(DEMO_TOTAL):
                run_demo_step(progress)
            snapshot = agent.snapshot(g.client_id)
            results.append(comparison_result_for(snapshot))
        result = agent.save_comparison_results(g.client_id, results)
    except OpenRouterError as exc:
        return error_response(str(exc), exc.status)
    except ValueError as exc:
        return error_response(str(exc), 400)

    return jsonify(with_demo_metadata(result, complete=True))


def run_demo_step(progress):
    state = agent.snapshot(g.client_id)
    active_strategy = state.get("active_strategy")
    step_number = progress + 1

    if active_strategy == "branching" and step_number in DEMO_BRANCH_SWITCHES:
        agent.switch_branch(g.client_id, DEMO_BRANCH_SWITCHES[step_number])

    result = agent.respond(g.client_id, DEMO_MESSAGES[progress])
    reply = result.get("reply")
    metadata = result.get("metadata")
    memory_update_error = result.get("memory_update_error")

    if active_strategy == "branching" and step_number == DEMO_BRANCH_CREATE_STEP:
        agent.create_checkpoint(g.client_id)
        result = agent.create_branches(g.client_id)

    agent.set_demo_progress(g.client_id, step_number)
    result = agent.snapshot(g.client_id)

    result["demo_step"] = step_number
    result["demo_message"] = DEMO_MESSAGES[progress]
    result["demo_progress"] = step_number
    result["reply"] = reply
    result["metadata"] = metadata
    if memory_update_error:
        result["memory_update_error"] = memory_update_error
    return result


def with_demo_metadata(data, complete=None):
    data = dict(data)
    progress = min(int(data.get("demo_progress", 0)), DEMO_TOTAL)
    data["demo_progress"] = progress
    data["demo_total"] = DEMO_TOTAL
    data["demo_complete"] = progress >= DEMO_TOTAL if complete is None else complete
    data["demo_timeline"] = DEMO_TIMELINE
    data["demo_call_warning"] = (
        "Run all strategies sends 84 main OpenRouter calls plus profile-memory update calls."
    )
    return data


def error_response(message, status):
    return jsonify({"error": message, "status": status}), status


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port)
