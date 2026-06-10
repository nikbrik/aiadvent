import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from token_counter import count_message_tokens, count_text_tokens, tokenizer_name


DEFAULT_PROVIDER = {"allow_fallbacks": False}
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
REASONING_EXCLUDED = {"exclude": True}
DEFAULT_CONTEXT_LIMIT = 4096
DEFAULT_MAX_TOKENS = 512
SYSTEM_PROMPT = (
    "You are a helpful chat assistant in a token-accounting demo. "
    "Keep answers concise unless the user asks for detail."
)

SHORT_DEMO_MESSAGES = [
    "Привет!",
    "Сколько будет 2+2?",
]

LONG_DEMO_MESSAGES = [
    "Начни длинный диалог про Python.",
    "Расскажи про list comprehensions.",
    "А про generators?",
    "Чем отличается tuple от list?",
    "Что такое декоратор?",
    "Как работает GIL?",
    "Когда использовать asyncio?",
    "Что такое dataclass?",
    "Как устроен dict?",
    "Дай короткий итог.",
]

OVERFLOW_FILLER = (
    "Это синтетическое сообщение для демонстрации переполнения контекста. "
    "Каждый повтор увеличивает prompt и историю. "
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state():
    return {
        "version": 1,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "messages": [],
        "turns": [],
        "cumulative": empty_cumulative(),
    }


def empty_cumulative():
    return {
        "prompt_tokens_estimated": 0,
        "prompt_tokens_actual": 0,
        "response_tokens_estimated": 0,
        "response_tokens_actual": 0,
        "total_tokens_estimated": 0,
        "total_tokens_actual": 0,
        "cost_estimated": 0.0,
        "cost_actual": 0.0,
    }


class FileMemoryStore:
    def __init__(self, root):
        self.root = Path(root)

    def path_for(self, client_id):
        safe_id = re.sub(r"[^a-fA-F0-9-]", "", client_id)
        if not safe_id:
            raise ValueError("client_id is invalid")
        return self.root / f"{safe_id}.json"

    def load(self, client_id):
        path = self.path_for(client_id)
        if not path.exists():
            return default_state()

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return default_state()

        return normalize_state(data)

    def save(self, client_id, state):
        path = self.path_for(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = utc_now()

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def clear(self, client_id):
        path = self.path_for(client_id)
        if path.exists():
            path.unlink()


class ChatAgent:
    def __init__(self, memory_store, llm):
        self.memory_store = memory_store
        self.llm = llm

    def snapshot(self, client_id):
        return public_state(self.memory_store.load(client_id))

    def clear(self, client_id):
        self.memory_store.clear(client_id)
        return public_state(default_state())

    def respond(self, client_id, message):
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")

        state = self.memory_store.load(client_id)
        return self._complete_turn(client_id, state, message)

    def run_demo_short(self, client_id):
        self.clear(client_id)
        last_result = None
        for message in SHORT_DEMO_MESSAGES:
            last_result = self.respond(client_id, message)
        return last_result

    def run_demo_long(self, client_id):
        self.clear(client_id)
        last_result = None
        for message in LONG_DEMO_MESSAGES:
            last_result = self.respond(client_id, message)
        return last_result

    def run_demo_overflow(self, client_id):
        self.clear(client_id)
        state = self.memory_store.load(client_id)
        context_limit = context_limit_value()
        response_budget = max_tokens_value()
        filler = overflow_filler_message(context_limit, response_budget)

        state["messages"].append({"role": "user", "content": filler})
        state["messages"].append({
            "role": "assistant",
            "content": "Синтетический ответ для заполнения истории перед overflow.",
        })

        result = self._complete_turn(
            client_id,
            state,
            "Ещё одно сообщение, которое должно превысить лимит контекста.",
            allow_prefill=True,
        )
        return result

    def _complete_turn(self, client_id, state, user_message, allow_prefill=False):
        model = model_value()
        history_messages = clean_messages(state.get("messages", []))
        current_request_tokens = count_text_tokens(user_message, model)
        history_tokens = count_message_tokens(history_messages, model)

        llm_messages = build_llm_messages(history_messages, user_message)
        prompt_tokens_estimated = count_message_tokens(llm_messages, model)
        response_budget = max_tokens_value()
        context_limit = context_limit_value()
        projected_total = prompt_tokens_estimated + response_budget

        turn_number = len(state.get("turns", [])) + 1
        turn = {
            "turn": turn_number,
            "status": "ok",
            "current_request_tokens": current_request_tokens,
            "history_tokens": history_tokens,
            "prompt_tokens_estimated": prompt_tokens_estimated,
            "prompt_tokens_actual": None,
            "response_tokens_estimated": 0,
            "response_tokens_actual": None,
            "total_tokens_actual": None,
            "turn_cost_actual": None,
            "turn_cost_estimated": None,
            "response_budget": response_budget,
            "context_limit": context_limit,
            "projected_total_tokens": projected_total,
            "model_called": False,
        }

        if projected_total > context_limit:
            turn["status"] = "overflow"
            turn["total_tokens_estimated"] = prompt_tokens_estimated
            turn["overflow"] = {
                "prompt_tokens_estimated": prompt_tokens_estimated,
                "context_limit": context_limit,
                "response_budget": response_budget,
                "over_by": projected_total - context_limit,
                "model_called": False,
            }
            state.setdefault("turns", []).append(turn)
            if not allow_prefill:
                state["messages"].append({"role": "user", "content": user_message})
            self.memory_store.save(client_id, state)
            return build_result(
                state,
                reply="",
                overflow=turn["overflow"],
                last_turn=turn,
            )

        completion = self.llm(
            messages=llm_messages,
            model=model,
            max_tokens=response_budget,
            provider=DEFAULT_PROVIDER,
            include_reasoning=False,
            reasoning=REASONING_EXCLUDED,
        )
        turn["model_called"] = True

        reply = str(completion.get("content") or "").strip()
        if not reply:
            reply = "OpenRouter/model не вернул видимый текст."

        prompt_tokens_actual = completion.get("prompt_tokens")
        response_tokens_actual = completion.get("completion_tokens")
        total_tokens_actual = completion.get("total_tokens")
        turn_cost_actual = completion.get("cost")

        response_tokens_estimated = count_text_tokens(reply, model)
        turn["prompt_tokens_actual"] = prompt_tokens_actual
        turn["response_tokens_actual"] = response_tokens_actual
        turn["response_tokens_estimated"] = response_tokens_estimated
        turn["total_tokens_actual"] = total_tokens_actual
        turn["turn_cost_actual"] = turn_cost_actual
        turn["turn_cost_estimated"] = estimate_turn_cost(
            prompt_tokens_actual if prompt_tokens_actual is not None else prompt_tokens_estimated,
            response_tokens_actual if response_tokens_actual is not None else response_tokens_estimated,
            turn_cost_actual,
        )
        turn["total_tokens_estimated"] = (
            int(turn["prompt_tokens_estimated"] or 0)
            + int(turn["response_tokens_estimated"] or 0)
        )

        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        state.setdefault("turns", []).append(turn)
        apply_turn_to_cumulative(state["cumulative"], turn)
        self.memory_store.save(client_id, state)

        return build_result(
            state,
            reply=reply,
            metadata=completion_metadata(completion),
            last_turn=turn,
        )


def normalize_state(data):
    state = default_state()
    if not isinstance(data, dict):
        return state

    state["messages"] = clean_messages(data.get("messages"))
    turns = data.get("turns")
    state["turns"] = turns if isinstance(turns, list) else []

    cumulative = data.get("cumulative")
    if isinstance(cumulative, dict):
        base = empty_cumulative()
        for key in base:
            if key in cumulative:
                base[key] = cumulative[key]
        state["cumulative"] = base
    return state


def public_state(state):
    context_limit = context_limit_value()
    pricing = pricing_state()
    last_turn = state.get("turns", [])[-1] if state.get("turns") else None
    prompt_tokens_estimated = last_turn.get("prompt_tokens_estimated") if last_turn else 0
    projected_total = (
        (last_turn.get("projected_total_tokens") if last_turn else 0)
        or prompt_tokens_estimated
    )

    return {
        "messages": deepcopy(state.get("messages", [])),
        "turns": deepcopy(state.get("turns", [])),
        "cumulative": deepcopy(state.get("cumulative", empty_cumulative())),
        "current_turn": deepcopy(last_turn) if last_turn else None,
        "context_limit": context_limit,
        "response_budget": max_tokens_value(),
        "model": model_value(),
        "tokenizer": tokenizer_name(),
        "pricing": pricing,
        "prompt_usage": {
            "prompt_tokens_estimated": prompt_tokens_estimated,
            "context_limit": context_limit,
            "response_budget": max_tokens_value(),
            "projected_total_tokens": projected_total,
            "remaining_tokens": max(0, context_limit - projected_total),
        },
    }


def build_result(state, reply="", metadata=None, overflow=None, last_turn=None):
    result = public_state(state)
    result["reply"] = reply
    if metadata:
        result["metadata"] = metadata
    if overflow:
        result["overflow"] = overflow
        result["error"] = format_overflow_message(overflow)
    if last_turn:
        result["last_turn"] = deepcopy(last_turn)
    return result


def format_overflow_message(overflow):
    return (
        "Preflight overflow: prompt "
        f"{overflow['prompt_tokens_estimated']} + budget "
        f"{overflow['response_budget']} > limit "
        f"{overflow['context_limit']} (over by {overflow['over_by']}). "
        "Model was not called."
    )


def build_llm_messages(history_messages, user_message):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history_messages,
        {"role": "user", "content": user_message},
    ]


def clean_messages(value):
    if not isinstance(value, list):
        return []
    messages = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


def apply_turn_to_cumulative(cumulative, turn):
    cumulative["prompt_tokens_estimated"] += int(turn.get("prompt_tokens_estimated") or 0)
    cumulative["response_tokens_estimated"] += int(turn.get("response_tokens_estimated") or 0)
    cumulative["total_tokens_estimated"] += int(turn.get("total_tokens_estimated") or 0)

    if turn.get("prompt_tokens_actual") is not None:
        cumulative["prompt_tokens_actual"] += int(turn["prompt_tokens_actual"])
    if turn.get("response_tokens_actual") is not None:
        cumulative["response_tokens_actual"] += int(turn["response_tokens_actual"])
    if turn.get("total_tokens_actual") is not None:
        cumulative["total_tokens_actual"] += int(turn["total_tokens_actual"])

    estimated = turn.get("turn_cost_estimated")
    if estimated is not None:
        cumulative["cost_estimated"] += float(estimated)

    actual = turn.get("turn_cost_actual")
    if actual is not None:
        cumulative["cost_actual"] += float(actual)


def pricing_state():
    prompt_price = env_float("PROMPT_PRICE_PER_1M_TOKENS")
    completion_price = env_float("COMPLETION_PRICE_PER_1M_TOKENS")
    configured = prompt_price is not None and completion_price is not None
    return {
        "configured": configured,
        "prompt_price_per_1m": prompt_price,
        "completion_price_per_1m": completion_price,
    }


def estimate_turn_cost(prompt_tokens, completion_tokens, actual_cost):
    if actual_cost is not None:
        return float(actual_cost)

    pricing = pricing_state()
    if not pricing["configured"]:
        return None

    prompt_part = (int(prompt_tokens or 0) * pricing["prompt_price_per_1m"]) / 1_000_000
    completion_part = (int(completion_tokens or 0) * pricing["completion_price_per_1m"]) / 1_000_000
    return prompt_part + completion_part


def overflow_filler_message(context_limit, response_budget):
    target = max(context_limit - response_budget, 256)
    chunk = OVERFLOW_FILLER
    repeats = max(1, (target // max(count_text_tokens(chunk), 1)) + 2)
    return chunk * repeats


def context_limit_value():
    return env_int("TOKEN_CONTEXT_LIMIT", DEFAULT_CONTEXT_LIMIT)


def max_tokens_value():
    return env_int("TOKEN_MAX_TOKENS", DEFAULT_MAX_TOKENS)


def model_value():
    return os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)


def env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def completion_metadata(completion):
    keys = (
        "id",
        "model",
        "finish_reason",
        "native_finish_reason",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "cost",
        "cost_details",
        "duration_ms",
    )
    return {key: completion.get(key) for key in keys if key in completion}
