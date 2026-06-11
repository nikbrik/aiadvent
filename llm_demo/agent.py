import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from token_counter import count_message_tokens, count_text_tokens, tokenizer_name

try:
    from llm_client import OpenRouterError
except ImportError:
    from .llm_client import OpenRouterError


DEFAULT_PROVIDER = {"allow_fallbacks": False}
# Budget OpenRouter default with 8K context so provider-overflow demo hits a real limit.
DEFAULT_MODEL = "meta-llama/llama-3-8b-instruct"
REASONING_EXCLUDED = {"exclude": True}
DEFAULT_CONTEXT_LIMIT = 4096
DEFAULT_MAX_TOKENS = 512
DEFAULT_OPENROUTER_MODEL_CONTEXT = 8192
DEFAULT_MEMORY_LOSS_OVERSHOOT = 2.0
DEFAULT_MEMORY_LOSS_TOKEN_SAFETY = 4.0
DEFAULT_MEMORY_LOSS_RECALL_MAX_TOKENS = 128
DEFAULT_MESSAGE_PREVIEW_CHARS = 400
DEFAULT_LOG_BODY_CHARS = 8000
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

PROVIDER_OVERFLOW_USER_MESSAGE = (
    "Provider overflow demo: запрос с max_tokens, который вместе с prompt "
    "превышает context window модели."
)

MEMORY_LOSS_CODEWORD = "BLUEFOX"
MEMORY_LOSS_SECRET_PROMPT = (
    f"Запомни кодовое слово: {MEMORY_LOSS_CODEWORD}. Ответь только «OK»."
)
MEMORY_LOSS_RECALL_PROMPT = (
    "Какое кодовое слово я назвал в самом первом сообщении этого диалога? "
    "Ответь одним словом, без пояснений."
)
MEMORY_LOSS_FILLER = (
    "Синтетический filler для memory-loss demo: история растёт, "
    "ранний факт из начала диалога может перестать попадать в контекст модели. "
    "OpenRouter может сжать или обрезать старые сообщения, когда prompt слишком длинный. "
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

    def run_demo_provider_overflow(self, client_id):
        self.clear(client_id)
        state = self.memory_store.load(client_id)
        return self._provider_overflow_turn(
            client_id,
            state,
            PROVIDER_OVERFLOW_USER_MESSAGE,
        )

    def run_demo_memory_loss(self, client_id):
        self.clear(client_id)
        state = self.memory_store.load(client_id)
        model = model_value()

        self._complete_turn(client_id, state, MEMORY_LOSS_SECRET_PROMPT)

        state = self.memory_store.load(client_id)
        prefill_pairs, prefill_history_tokens = build_memory_loss_prefill(
            state.get("messages", []),
            model,
        )
        for index, (user_text, assistant_text) in enumerate(prefill_pairs, start=1):
            state["messages"].append({"role": "user", "content": user_text})
            state["messages"].append({"role": "assistant", "content": assistant_text})
        self.memory_store.save(client_id, state)

        state = self.memory_store.load(client_id)
        from llm_client import DISABLE_CONTEXT_COMPRESSION

        full_history = clean_messages(state.get("messages", []))
        model_context = openrouter_model_context()
        recall_max_tokens = memory_loss_recall_max_tokens()
        prompt_budget = memory_loss_local_prompt_budget(model_context, recall_max_tokens)
        prompt_full_estimated = count_message_tokens(
            build_llm_messages(full_history, MEMORY_LOSS_RECALL_PROMPT),
            model,
        )
        truncated_history, dropped_messages = truncate_history_for_model_window(
            full_history,
            MEMORY_LOSS_RECALL_PROMPT,
            model,
            prompt_budget,
        )

        try:
            result = self._complete_turn(
                client_id,
                state,
                MEMORY_LOSS_RECALL_PROMPT,
                skip_preflight=True,
                demo="memory_loss",
                llm_history_override=truncated_history,
                llm_plugins=DISABLE_CONTEXT_COMPRESSION,
                llm_max_tokens=recall_max_tokens,
                turn_extras={
                    "prompt_tokens_full_estimated": prompt_full_estimated,
                    "local_prompt_budget": prompt_budget,
                    "token_safety_multiplier": memory_loss_token_safety_multiplier(),
                    "messages_dropped_from_head": dropped_messages,
                    "context_compression_disabled": True,
                    "truncation_strategy": "drop_oldest_until_fits",
                    "model_context_limit": model_context,
                    "codeword_in_llm_payload": codeword_in_history(truncated_history),
                },
            )
        except OpenRouterError as exc:
            return self._memory_loss_provider_failure_result(
                client_id,
                state,
                exc,
                prefill_pairs=len(prefill_pairs),
                prefill_history_tokens=prefill_history_tokens,
                prompt_full_estimated=prompt_full_estimated,
                prompt_budget=prompt_budget,
                dropped_messages=dropped_messages,
                truncated_history=truncated_history,
                recall_max_tokens=recall_max_tokens,
                model_context=model_context,
            )

        memory_loss = build_memory_loss_result(
            result.get("reply", ""),
            prefill_pairs=len(prefill_pairs),
            prefill_history_tokens=prefill_history_tokens,
            recall_turn=result.get("last_turn") or {},
            target_prompt_tokens=memory_loss_target_prompt_tokens(),
        )
        result["memory_loss"] = memory_loss
        if result.get("last_turn") is not None:
            result["last_turn"]["memory_loss"] = memory_loss
            result["last_turn"]["demo"] = "memory_loss"

        state = self.memory_store.load(client_id)
        if state.get("turns"):
            state["turns"][-1]["memory_loss"] = memory_loss
            state["turns"][-1]["demo"] = "memory_loss"
            self.memory_store.save(client_id, state)

        if not memory_loss["recalled_correctly"]:
            result["error"] = memory_loss["summary"]
        return result

    def _memory_loss_provider_failure_result(
        self,
        client_id,
        state,
        exc,
        prefill_pairs,
        prefill_history_tokens,
        prompt_full_estimated,
        prompt_budget,
        dropped_messages,
        truncated_history,
        recall_max_tokens,
        model_context,
    ):
        turn_number = len(state.get("turns", [])) + 1
        prompt_sent_estimated = count_message_tokens(
            build_llm_messages(truncated_history, MEMORY_LOSS_RECALL_PROMPT),
            model_value(),
        )
        turn = {
            "turn": turn_number,
            "status": "provider_error",
            "demo": "memory_loss",
            "current_request_tokens": count_text_tokens(MEMORY_LOSS_RECALL_PROMPT, model_value()),
            "history_tokens": count_message_tokens(state.get("messages", []), model_value()),
            "prompt_tokens_estimated": prompt_sent_estimated,
            "prompt_tokens_full_estimated": prompt_full_estimated,
            "local_prompt_budget": prompt_budget,
            "messages_dropped_from_head": dropped_messages,
            "context_compression_disabled": True,
            "model_context_limit": model_context,
            "codeword_in_llm_payload": codeword_in_history(truncated_history),
            "response_budget": recall_max_tokens,
            "model_called": True,
            "preflight_skipped": True,
            "provider_error": {
                "message": str(exc),
                "http_status": exc.status,
                "context_compression_disabled": True,
            },
        }
        state["messages"].append({"role": "user", "content": MEMORY_LOSS_RECALL_PROMPT})
        state.setdefault("turns", []).append(turn)
        self.memory_store.save(client_id, state)

        memory_loss = {
            "demo": "memory_loss",
            "expected_codeword": MEMORY_LOSS_CODEWORD,
            "model_answer": "",
            "recalled_correctly": False,
            "prefill_pairs": prefill_pairs,
            "prefill_history_tokens": prefill_history_tokens,
            "recall_prompt_tokens_estimated": prompt_sent_estimated,
            "recall_prompt_tokens_actual": None,
            "recall_prompt_tokens_full_estimated": prompt_full_estimated,
            "messages_dropped_from_head": dropped_messages,
            "codeword_in_llm_payload": codeword_in_history(truncated_history),
            "local_prompt_budget": prompt_budget,
            "model_context_limit": model_context,
            "context_compression_disabled": True,
            "truncation_strategy": "drop_oldest_until_fits",
            "summary": (
                f"Recall не прошёл: OpenRouter HTTP {exc.status}. "
                f"Локальная оценка prompt≈{prompt_sent_estimated}, budget≈{prompt_budget}. "
                "Увеличьте MEMORY_LOSS_TOKEN_SAFETY или уменьшите MEMORY_LOSS_OVERSHOOT."
            ),
        }
        turn["memory_loss"] = memory_loss
        result = build_result(
            state,
            reply="",
            provider_error=turn["provider_error"],
            last_turn=turn,
            error=memory_loss["summary"],
        )
        result["memory_loss"] = memory_loss
        return result

    def _complete_turn(
        self,
        client_id,
        state,
        user_message,
        allow_prefill=False,
        skip_preflight=False,
        demo=None,
        llm_history_override=None,
        llm_plugins=None,
        llm_max_tokens=None,
        turn_extras=None,
    ):
        model = model_value()
        full_history = clean_messages(state.get("messages", []))
        history_messages = (
            clean_messages(llm_history_override)
            if llm_history_override is not None
            else full_history
        )
        current_request_tokens = count_text_tokens(user_message, model)
        history_tokens = count_message_tokens(full_history, model)

        llm_messages = build_llm_messages(history_messages, user_message)
        prompt_tokens_estimated = count_message_tokens(llm_messages, model)
        response_budget = llm_max_tokens if llm_max_tokens is not None else max_tokens_value()
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
        if skip_preflight:
            turn["preflight_skipped"] = True
        if demo:
            turn["demo"] = demo
        if turn_extras:
            turn.update(turn_extras)

        if not skip_preflight and projected_total > context_limit:
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
            plugins=llm_plugins,
        )
        return self._finalize_success_turn(
            client_id,
            state,
            user_message,
            turn,
            completion,
            model,
        )

    def _provider_overflow_turn(self, client_id, state, user_message, allow_prefill=False):
        from llm_client import DISABLE_CONTEXT_COMPRESSION

        model = model_value()
        history_messages = clean_messages(state.get("messages", []))
        current_request_tokens = count_text_tokens(user_message, model)
        history_tokens = count_message_tokens(history_messages, model)

        llm_messages = build_llm_messages(history_messages, user_message)
        prompt_tokens_estimated = count_message_tokens(llm_messages, model)
        model_context = openrouter_model_context()
        response_budget = provider_overflow_max_tokens_value()
        local_context_limit = context_limit_value()
        projected_total = prompt_tokens_estimated + response_budget

        turn_number = len(state.get("turns", [])) + 1
        turn = {
            "turn": turn_number,
            "status": "provider_error",
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
            "context_limit": local_context_limit,
            "model_context_limit": model_context,
            "projected_total_tokens": projected_total,
            "model_called": True,
            "preflight_skipped": True,
            "context_compression_disabled": True,
            "overflow_strategy": "max_tokens",
        }

        try:
            completion = self.llm(
                messages=llm_messages,
                model=model,
                max_tokens=response_budget,
                provider=DEFAULT_PROVIDER,
                include_reasoning=False,
                reasoning=REASONING_EXCLUDED,
                plugins=DISABLE_CONTEXT_COMPRESSION,
            )
        except OpenRouterError as exc:
            turn["status"] = "provider_error"
            turn["total_tokens_estimated"] = prompt_tokens_estimated
            turn["provider_error"] = {
                "message": str(exc),
                "http_status": exc.status,
                "context_compression_disabled": True,
                "overflow_strategy": "max_tokens",
                "model_context_limit": model_context,
                "requested_max_tokens": response_budget,
            }
            state.setdefault("turns", []).append(turn)
            if not allow_prefill:
                state["messages"].append({"role": "user", "content": user_message})
            self.memory_store.save(client_id, state)
            return build_result(
                state,
                reply="",
                provider_error=turn["provider_error"],
                last_turn=turn,
                error=format_provider_error_message(turn["provider_error"]),
            )

        turn["status"] = "provider_unexpected_ok"
        turn["provider_warning"] = (
            f"OpenRouter принял запрос: prompt≈{prompt_tokens_estimated} + "
            f"max_tokens={response_budget} не превысили context window модели "
            f"({model_context}). Увеличь OPENROUTER_MODEL_CONTEXT или выбери модель с "
            "меньшим окном, если нужна ошибка 400."
        )
        return self._finalize_success_turn(
            client_id,
            state,
            user_message,
            turn,
            completion,
            model,
            allow_prefill=allow_prefill,
            provider_warning=turn["provider_warning"],
        )

    def _finalize_success_turn(
        self,
        client_id,
        state,
        user_message,
        turn,
        completion,
        model,
        allow_prefill=False,
        provider_warning=None,
    ):
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
            prompt_tokens_actual if prompt_tokens_actual is not None else turn["prompt_tokens_estimated"],
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

        result = build_result(
            state,
            reply=reply,
            metadata=completion_metadata(completion),
            last_turn=turn,
        )
        if provider_warning:
            result["provider_warning"] = provider_warning
            result["error"] = provider_warning
        return result


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
        "messages": public_messages(state.get("messages", [])),
        "turns": deepcopy(state.get("turns", [])),
        "cumulative": deepcopy(state.get("cumulative", empty_cumulative())),
        "current_turn": deepcopy(last_turn) if last_turn else None,
        "context_limit": context_limit,
        "openrouter_model_context": openrouter_model_context(),
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


def build_result(state, reply="", metadata=None, overflow=None, provider_error=None, last_turn=None, error=None):
    result = public_state(state)
    result["reply"] = reply
    if metadata:
        result["metadata"] = metadata
    if overflow:
        result["overflow"] = overflow
        result["error"] = error or format_overflow_message(overflow)
    if provider_error:
        result["provider_error"] = provider_error
        result["error"] = error or format_provider_error_message(provider_error)
    elif error:
        result["error"] = error
    if last_turn:
        result["last_turn"] = deepcopy(last_turn)
    return result


def format_provider_error_message(provider_error):
    status = provider_error.get("http_status")
    prefix = f"OpenRouter HTTP {status}: " if status else "OpenRouter error: "
    suffix = (
        " Context-compression was disabled for this request."
        if provider_error.get("context_compression_disabled")
        else ""
    )
    return prefix + str(provider_error.get("message") or "Unknown provider error") + suffix


def format_overflow_message(overflow):
    return (
        "Preflight overflow: prompt "
        f"{overflow['prompt_tokens_estimated']} + budget "
        f"{overflow['response_budget']} > limit "
        f"{overflow['context_limit']} (over by {overflow['over_by']}). "
        "Model was not called."
    )


def public_messages(messages):
    preview_limit = message_preview_chars()
    public = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        entry = {
            "role": item.get("role"),
            "content": content,
        }
        if len(content) > preview_limit:
            entry["content"] = (
                f"{content[:preview_limit]}… "
                f"[truncated: {len(content)} chars total, showing {preview_limit}]"
            )
            entry["content_truncated"] = True
            entry["content_length"] = len(content)
        public.append(entry)
    return public


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


def build_memory_loss_prefill(messages, model):
    target_prompt = memory_loss_target_prompt_tokens()
    response_budget = max_tokens_value()
    pairs = []
    working = clean_messages(messages)
    safety_limit = 800

    while len(pairs) < safety_limit:
        index = len(pairs) + 1
        user_text = (
            f"Ход {index}: продолжи коротко про Python — одно предложение про списки, "
            "генераторы или декораторы."
        )
        assistant_text = memory_loss_filler_block(index)
        candidate = working + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
        prompt_estimated = count_message_tokens(
            build_llm_messages(candidate, MEMORY_LOSS_RECALL_PROMPT),
            model,
        )
        if prompt_estimated >= target_prompt:
            break
        working = candidate
        pairs.append((user_text, assistant_text))

    return pairs, count_message_tokens(working, model)


def memory_loss_filler_block(index):
    paragraph = MEMORY_LOSS_FILLER * 6
    return (
        f"Ход {index}. {paragraph} "
        f"Это длинный синтетический ответ #{index}, чтобы вытеснить ранние сообщения из окна."
    )


def memory_loss_target_prompt_tokens():
    model_context = openrouter_model_context()
    overshoot = env_float("MEMORY_LOSS_OVERSHOOT")
    if overshoot is None or overshoot <= 0:
        overshoot = DEFAULT_MEMORY_LOSS_OVERSHOOT
    return int(model_context * overshoot)


def memory_loss_overshoot_value():
    overshoot = env_float("MEMORY_LOSS_OVERSHOOT")
    if overshoot is None or overshoot <= 0:
        return DEFAULT_MEMORY_LOSS_OVERSHOOT
    return overshoot


def memory_loss_token_safety_multiplier():
    safety = env_float("MEMORY_LOSS_TOKEN_SAFETY")
    if safety is None or safety <= 0:
        return DEFAULT_MEMORY_LOSS_TOKEN_SAFETY
    return safety


def memory_loss_recall_max_tokens():
    return env_int("MEMORY_LOSS_RECALL_MAX_TOKENS", DEFAULT_MEMORY_LOSS_RECALL_MAX_TOKENS)


def memory_loss_local_prompt_budget(model_context, response_budget):
    safety = memory_loss_token_safety_multiplier()
    return max(256, int((model_context - response_budget) / safety))


def evaluate_codeword_recall(reply, expected):
    if not reply:
        return False
    reply_clean = re.sub(r"[^A-Za-z0-9]", "", str(reply)).upper()
    expected_clean = re.sub(r"[^A-Za-z0-9]", "", str(expected)).upper()
    if not expected_clean:
        return False
    return reply_clean == expected_clean or expected_clean in reply_clean


def truncate_history_for_model_window(
    history_messages,
    user_message,
    model,
    prompt_budget,
):
    working = clean_messages(history_messages)
    original_len = len(working)

    while working:
        prompt_estimated = count_message_tokens(
            build_llm_messages(working, user_message),
            model,
        )
        if prompt_estimated <= prompt_budget:
            break
        working = working[1:]

    return working, original_len - len(working)


def codeword_in_history(messages, codeword=MEMORY_LOSS_CODEWORD):
    return any(codeword in str(item.get("content") or "") for item in messages)


def build_memory_loss_result(
    reply,
    prefill_pairs,
    prefill_history_tokens,
    recall_turn,
    target_prompt_tokens,
):
    recalled = evaluate_codeword_recall(reply, MEMORY_LOSS_CODEWORD)
    model_context = openrouter_model_context()
    prompt_estimated = int(recall_turn.get("prompt_tokens_estimated") or 0)
    prompt_actual = recall_turn.get("prompt_tokens_actual")
    prompt_full_estimated = int(recall_turn.get("prompt_tokens_full_estimated") or 0)
    dropped_messages = int(recall_turn.get("messages_dropped_from_head") or 0)
    codeword_in_payload = bool(recall_turn.get("codeword_in_llm_payload"))
    overshoot = memory_loss_overshoot_value()

    if recalled:
        summary = (
            f"Модель ответила «{MEMORY_LOSS_CODEWORD}». "
            f"В payload {'есть' if codeword_in_payload else 'нет'} кодовое слово; "
            f"отброшено {dropped_messages} старых сообщений."
        )
    else:
        summary = (
            f"Модель ответила «{str(reply).strip()}», ожидалось «{MEMORY_LOSS_CODEWORD}». "
            f"Полная история ≈{prompt_full_estimated} tokens, в API ушло ≈{prompt_estimated} "
            f"(actual {prompt_actual if prompt_actual is not None else '—'}). "
            f"С начала истории отброшено {dropped_messages} сообщений — "
            f"{'включая' if not codeword_in_payload else 'но'} сообщение с кодовым словом "
            f"{'не попало' if not codeword_in_payload else 'всё ещё попало'} в prompt."
        )

    return {
        "demo": "memory_loss",
        "expected_codeword": MEMORY_LOSS_CODEWORD,
        "model_answer": str(reply or "").strip(),
        "recalled_correctly": recalled,
        "prefill_pairs": prefill_pairs,
        "prefill_history_tokens": prefill_history_tokens,
        "recall_prompt_tokens_estimated": prompt_estimated,
        "recall_prompt_tokens_actual": prompt_actual,
        "recall_prompt_tokens_full_estimated": prompt_full_estimated,
        "local_prompt_budget": recall_turn.get("local_prompt_budget"),
        "messages_dropped_from_head": dropped_messages,
        "codeword_in_llm_payload": codeword_in_payload,
        "target_prompt_tokens": target_prompt_tokens,
        "overshoot_ratio": overshoot,
        "model_context_limit": model_context,
        "context_compression_disabled": True,
        "truncation_strategy": recall_turn.get("truncation_strategy"),
        "summary": summary,
    }


def openrouter_model_context():
    return env_int("OPENROUTER_MODEL_CONTEXT", DEFAULT_OPENROUTER_MODEL_CONTEXT)


def provider_overflow_max_tokens_value():
    return openrouter_model_context()


def message_preview_chars():
    return env_int("MESSAGE_PREVIEW_CHARS", DEFAULT_MESSAGE_PREVIEW_CHARS)


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
