import json
import logging
import os
import threading
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
demo_stop_lock = threading.Lock()
demo_stop_requests = set()


class DemoRunStopped(Exception):
    pass


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
    return run_active_demo(reset=True)


@app.post("/api/demo/start-active")
def demo_start_active():
    state = agent.snapshot(g.client_id)
    active_strategy = state.get("active_strategy")
    clear_demo_stop(g.client_id)
    agent.reset_strategy(g.client_id, active_strategy)
    agent.set_demo_progress(g.client_id, 0)
    agent.set_strategy(g.client_id, active_strategy)
    save_active_run(active_strategy, 0)
    result = agent.snapshot(g.client_id)
    result["demo_live_run"] = True
    return jsonify(with_demo_metadata(result, complete=False))


@app.post("/api/demo/continue")
def demo_continue():
    run_state = agent.snapshot(g.client_id).get("demo_run") or {}
    if run_state.get("mode") == "active":
        return run_active_demo(reset=False)
    if run_state.get("mode") == "all":
        return run_all_demo(reset=False)
    return error_response("No resumable demo run was found", 400)


def run_active_demo(reset):
    state = agent.snapshot(g.client_id)
    run_state = state.get("demo_run") or {}
    active_strategy = run_state.get("strategy_id") if not reset else state.get("active_strategy")
    progress = int(run_state.get("progress") or 0) if not reset else 0
    try:
        clear_demo_stop(g.client_id)
        if reset:
            agent.reset_strategy(g.client_id, active_strategy)
            agent.set_demo_progress(g.client_id, 0)
        agent.set_strategy(g.client_id, active_strategy)
        save_active_run(active_strategy, progress)
        result = None
        for step_index in range(progress, DEMO_TOTAL):
            result = run_demo_step(step_index, allow_stop=True)
            save_active_run(active_strategy, step_index + 1)
    except OpenRouterError as exc:
        return recover_demo_error(str(exc), exc.status)
    except ValueError as exc:
        return recover_demo_error(str(exc), 400)
    except DemoRunStopped:
        clear_demo_stop(g.client_id)
        result = agent.snapshot(g.client_id)
        result["demo_stopped"] = True
        return jsonify(with_demo_metadata(result, complete=False))

    agent.clear_demo_run(g.client_id)
    return jsonify(with_demo_metadata(result or agent.snapshot(g.client_id), complete=True))


@app.post("/api/demo/run-all")
def demo_run_all():
    return run_all_demo(reset=True)


@app.post("/api/demo/start-all")
def demo_start_all():
    clear_demo_stop(g.client_id)
    agent.reset_demo(g.client_id)
    agent.save_comparison_results(g.client_id, [])
    save_all_run(0, 0, [])
    result = agent.snapshot(g.client_id)
    result["demo_live_run"] = True
    return jsonify(with_demo_metadata(result, complete=False))


@app.post("/api/demo/continue-step")
def demo_continue_step():
    try:
        result = continue_demo_one_step()
    except OpenRouterError as exc:
        return recover_demo_error(str(exc), exc.status)
    except ValueError as exc:
        return recover_demo_error(str(exc), 400)
    except DemoRunStopped:
        clear_demo_stop(g.client_id)
        result = agent.snapshot(g.client_id)
        result["demo_stopped"] = True
        return jsonify(with_demo_metadata(result, complete=False))
    return jsonify(with_demo_metadata(result, complete=not (result.get("demo_run") or {}).get("mode")))


def run_all_demo(reset):
    state = agent.snapshot(g.client_id)
    run_state = state.get("demo_run") or {}
    results = [] if reset else list(run_state.get("results") or state.get("comparison_results") or [])
    start_index = int(run_state.get("strategy_index") or 0) if not reset else 0
    start_progress = int(run_state.get("progress") or 0) if not reset else 0
    try:
        clear_demo_stop(g.client_id)
        if reset:
            agent.reset_demo(g.client_id)
            agent.save_comparison_results(g.client_id, [])
        save_all_run(start_index, start_progress, results)
        for strategy_index in range(start_index, len(STRATEGY_IDS)):
            strategy_id = STRATEGY_IDS[strategy_index]
            ensure_demo_not_stopped(g.client_id)
            agent.set_strategy(g.client_id, strategy_id)
            if reset or strategy_index != start_index or start_progress == 0:
                agent.reset_strategy(g.client_id, strategy_id)
                agent.set_demo_progress(g.client_id, 0)
                start_progress = 0
            save_all_run(strategy_index, start_progress, results, strategy_id=strategy_id)
            for step_index in range(start_progress, DEMO_TOTAL):
                run_demo_step(step_index, allow_stop=True)
                save_all_run(strategy_index, step_index + 1, results, strategy_id=strategy_id)
            snapshot = agent.snapshot(g.client_id)
            results.append(comparison_result_for(snapshot))
            agent.save_comparison_results(g.client_id, results)
            save_all_run(strategy_index + 1, 0, results)
            start_progress = 0
        result = agent.save_comparison_results(g.client_id, results)
    except OpenRouterError as exc:
        return recover_demo_error(str(exc), exc.status)
    except ValueError as exc:
        return recover_demo_error(str(exc), 400)
    except DemoRunStopped:
        clear_demo_stop(g.client_id)
        result = agent.save_comparison_results(g.client_id, results)
        result["demo_stopped"] = True
        return jsonify(with_demo_metadata(result, complete=False))

    agent.clear_demo_run(g.client_id)
    return jsonify(with_demo_metadata(result, complete=True))


@app.post("/api/demo/stop")
def demo_stop():
    request_demo_stop(g.client_id)
    result = agent.snapshot(g.client_id)
    result["demo_stopping"] = True
    return jsonify(with_demo_metadata(result, complete=False))


def run_demo_step(progress, allow_stop=False):
    if allow_stop:
        ensure_demo_not_stopped(g.client_id)

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


def continue_demo_one_step():
    ensure_demo_not_stopped(g.client_id)
    state = agent.snapshot(g.client_id)
    run_state = state.get("demo_run") or {}
    mode = run_state.get("mode")
    if mode == "active":
        return continue_active_one_step(run_state)
    if mode == "all":
        return continue_all_one_step(run_state)
    raise ValueError("No resumable demo run was found")


def continue_active_one_step(run_state):
    strategy_id = run_state.get("strategy_id") or agent.snapshot(g.client_id).get("active_strategy")
    progress = int(run_state.get("progress") or 0)
    if progress >= DEMO_TOTAL:
        agent.clear_demo_run(g.client_id)
        result = agent.snapshot(g.client_id)
        result["demo_live_run"] = True
        return result

    agent.set_strategy(g.client_id, strategy_id)
    result = run_demo_step(progress, allow_stop=True)
    save_active_run(strategy_id, progress + 1)

    if progress + 1 >= DEMO_TOTAL:
        agent.clear_demo_run(g.client_id)
        result = agent.snapshot(g.client_id)
        result["demo_complete"] = True
    else:
        result = agent.snapshot(g.client_id)
    result["demo_live_run"] = True
    result["demo_step"] = progress + 1
    result["demo_message"] = DEMO_MESSAGES[progress]
    return result


def continue_all_one_step(run_state):
    results = list(run_state.get("results") or [])
    strategy_index = int(run_state.get("strategy_index") or 0)
    progress = int(run_state.get("progress") or 0)

    if strategy_index >= len(STRATEGY_IDS):
        result = agent.save_comparison_results(g.client_id, results)
        agent.clear_demo_run(g.client_id)
        result = agent.snapshot(g.client_id)
        result["demo_live_run"] = True
        return result

    strategy_id = STRATEGY_IDS[strategy_index]
    agent.set_strategy(g.client_id, strategy_id)
    if progress == 0:
        agent.reset_strategy(g.client_id, strategy_id)
        agent.set_demo_progress(g.client_id, 0)

    result = run_demo_step(progress, allow_stop=True)
    progress += 1
    save_all_run(strategy_index, progress, results, strategy_id=strategy_id)

    if progress >= DEMO_TOTAL:
        snapshot = agent.snapshot(g.client_id)
        results.append(comparison_result_for(snapshot))
        agent.save_comparison_results(g.client_id, results)
        save_all_run(strategy_index + 1, 0, results)
        if strategy_index + 1 >= len(STRATEGY_IDS):
            agent.clear_demo_run(g.client_id)

    result = agent.snapshot(g.client_id)
    result["demo_live_run"] = True
    result["demo_step"] = progress
    result["demo_message"] = DEMO_MESSAGES[progress - 1]
    return result


def save_active_run(strategy_id, progress, error=""):
    agent.save_demo_run(g.client_id, {
        "mode": "active",
        "strategy_id": strategy_id,
        "strategy_index": STRATEGY_IDS.index(strategy_id) if strategy_id in STRATEGY_IDS else 0,
        "progress": progress,
        "results": [],
        "error": error,
    })


def save_all_run(strategy_index, progress, results, strategy_id=""):
    if not strategy_id and 0 <= strategy_index < len(STRATEGY_IDS):
        strategy_id = STRATEGY_IDS[strategy_index]
    agent.save_demo_run(g.client_id, {
        "mode": "all",
        "strategy_id": strategy_id,
        "strategy_index": strategy_index,
        "progress": progress,
        "results": results,
        "error": "",
    })


def recover_demo_error(message, status):
    state = agent.snapshot(g.client_id)
    run_state = dict(state.get("demo_run") or {})
    run_state["error"] = message
    agent.save_demo_run(g.client_id, run_state)
    state = agent.snapshot(g.client_id)
    state["demo_error"] = message
    state["demo_error_status"] = status
    state["demo_resumable"] = True
    return jsonify(with_demo_metadata(state, complete=False))


def request_demo_stop(client_id):
    with demo_stop_lock:
        demo_stop_requests.add(client_id)


def clear_demo_stop(client_id):
    with demo_stop_lock:
        demo_stop_requests.discard(client_id)


def ensure_demo_not_stopped(client_id):
    with demo_stop_lock:
        stopped = client_id in demo_stop_requests
    if stopped:
        raise DemoRunStopped()


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
