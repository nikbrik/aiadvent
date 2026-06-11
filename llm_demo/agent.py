import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

try:
    from context_compression import (
        append_summary_block,
        build_payload_preview,
        compression_config,
        compression_enabled,
        default_compression,
        ensure_compression_fields,
        maybe_compress_history,
        reset_compression,
        select_history_messages,
    )
    from quality_judge import quality_delta, safe_judge_answer
    from token_counter import count_message_tokens, count_text_tokens, tokenizer_name
except ImportError:
    from .context_compression import (
        append_summary_block,
        build_payload_preview,
        compression_config,
        compression_enabled,
        default_compression,
        ensure_compression_fields,
        maybe_compress_history,
        reset_compression,
        select_history_messages,
    )
    from .quality_judge import quality_delta, safe_judge_answer
    from .token_counter import count_message_tokens, count_text_tokens, tokenizer_name


DEFAULT_PROVIDER = {"allow_fallbacks": False}
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
REASONING_EXCLUDED = {"exclude": True}
MAX_ARCHIVED_SUMMARIES = 8
MAX_SUMMARY_CHARS = 900
DEFAULT_MAX_STORED_MESSAGES = 200
DEFAULT_MAX_STORED_TURNS = 200

COMPARE_SECRET_PROMPT = (
    "Запомни: кодовое слово BLUEFOX, любимый язык Kotlin, проект Orbit. "
    "Ответь только «OK»."
)
COMPARE_RECALL_PROMPT = (
    "Назови кодовое слово, любимый язык и проект из первого сообщения. "
    "Кратко, по пунктам."
)
COMPARE_GROUND_TRUTH = {
    "codeword": "BLUEFOX",
    "language": "Kotlin",
    "project": "Orbit",
}
COMPARE_FILLER_MESSAGES = [
    "Расскажи про list comprehensions в Python.",
    "А про generators?",
    "Чем tuple отличается от list?",
    "Что такое декоратор?",
    "Как работает GIL?",
    "Когда использовать asyncio?",
    "Что такое dataclass?",
    "Как устроен dict?",
    "Что такое context manager?",
    "Чем отличаются append и extend?",
    "Что такое lambda?",
    "Дай короткий итог по Python.",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_chat_id():
    return str(uuid.uuid4())


def empty_cumulative():
    return {
        "prompt_tokens_estimated": 0,
        "prompt_tokens_full_estimated": 0,
        "response_tokens_estimated": 0,
        "response_tokens_actual": 0,
        "summarization_tokens_estimated": 0,
        "total_tokens_estimated": 0,
        "total_tokens_actual": 0,
        "tokens_net_saved": 0,
        "cost_actual": 0.0,
        "cost_estimated": 0.0,
    }


def default_memory():
    return {
        "version": 2,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "profile": {
            "style": "",
            "facts": [],
            "inferences": [],
        },
        "current_chat": {
            "id": new_chat_id(),
            "started_at": utc_now(),
            "summary": "",
            "messages": [],
        },
        "history_summary": "",
        "compression": default_compression(),
        "archived_chats": [],
        "turns": [],
        "cumulative": empty_cumulative(),
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
            return default_memory()

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return default_memory()

        return normalize_memory(data)

    def save(self, client_id, memory):
        path = self.path_for(client_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = utc_now()

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(memory, handle, ensure_ascii=False, indent=2)
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
        return public_memory(self.memory_store.load(client_id))

    def clear(self, client_id):
        self.memory_store.clear(client_id)
        return public_memory(default_memory())

    def start_new_chat(self, client_id):
        memory = self.memory_store.load(client_id)
        archive_current_chat(memory)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def resume_chat(self, client_id, chat_id):
        memory = self.memory_store.load(client_id)
        chat_id = str(chat_id or "").strip()
        archived = memory.get("archived_chats", [])
        index = next(
            (
                position
                for position, chat in enumerate(archived)
                if chat.get("id") == chat_id and chat.get("messages")
            ),
            None,
        )
        if index is None:
            raise ValueError("archived chat was not found")

        restored = archived.pop(index)
        archive_current_chat(memory)
        memory["current_chat"] = {
            "id": restored.get("id") or new_chat_id(),
            "started_at": restored.get("started_at") or utc_now(),
            "summary": restored.get("summary", ""),
            "messages": clean_messages(restored.get("messages"), limit=None),
        }
        reset_compression(memory)
        memory["current_chat"]["summary"] = ""
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def respond(self, client_id, message, compression=None):
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")

        memory = self.memory_store.load(client_id)
        if compression is not None:
            ensure_compression_fields(memory)
            memory["compression"]["enabled"] = bool(compression)

        return self._complete_turn(client_id, memory, message)

    def run_demo_compression_compare(self, client_id):
        del client_id
        off_id = str(uuid.uuid4())
        on_id = str(uuid.uuid4())
        script = [COMPARE_SECRET_PROMPT, *COMPARE_FILLER_MESSAGES, COMPARE_RECALL_PROMPT]

        without = self._run_compare_track(off_id, script, compression=False)
        with_track = self._run_compare_track(on_id, script, compression=True)

        self.memory_store.clear(off_id)
        self.memory_store.clear(on_id)

        without_score = without["judge"]["score"]
        with_score = with_track["judge"]["score"]
        tokens_saved = (
            without["tokens"]["cumulative_prompt_full_estimated"]
            - with_track["tokens"]["cumulative_prompt_estimated"]
            - with_track["tokens"]["cumulative_summarization_estimated"]
        )

        return {
            "comparison": {
                "without": without,
                "with": with_track,
                "tokens_saved": tokens_saved,
                "quality_delta": quality_delta(without_score, with_score),
            }
        }

    def _run_compare_track(self, client_id, script, compression):
        self.memory_store.clear(client_id)
        memory = self.memory_store.load(client_id)
        ensure_compression_fields(memory)
        memory["compression"]["enabled"] = compression
        self.memory_store.save(client_id, memory)

        last_result = None
        for index, message in enumerate(script):
            memory = self.memory_store.load(client_id)
            run_judge = index == len(script) - 1
            last_result = self._complete_turn(
                client_id,
                memory,
                message,
                run_judge=run_judge,
            )

        return {
            "compression": compression,
            "answer": last_result.get("reply", ""),
            "judge": last_result.get("judge") or {},
            "summary": last_result.get("history_summary", ""),
            "tokens": token_summary(last_result),
        }

    def _complete_turn(self, client_id, memory, user_message, run_judge=False):
        ensure_compression_fields(memory)
        model = model_value()
        enabled = compression_enabled(memory)
        full_history = clean_messages(memory["current_chat"]["messages"], limit=None)

        summarization_events = []
        if enabled:
            summarization_events = maybe_compress_history(
                memory,
                self.llm,
                model,
                agent_options(),
            )

        history_messages, history_meta = select_history_messages(memory, enabled)
        system_prompt = build_system_prompt(memory, include_history_summary=enabled)
        llm_messages = [
            {"role": "system", "content": system_prompt},
            *history_messages,
            {"role": "user", "content": user_message},
        ]

        full_llm_messages = build_full_llm_messages(memory, user_message)
        current_request_tokens = count_text_tokens(user_message, model)
        history_tokens_full = count_message_tokens(full_history, model)
        history_tokens_sent = count_message_tokens(history_messages, model)
        prompt_tokens_estimated = count_message_tokens(llm_messages, model)
        prompt_tokens_full_estimated = count_message_tokens(full_llm_messages, model)
        summarization_tokens_estimated = sum(
            int(event.get("summarization_tokens_estimated") or 0)
            for event in summarization_events
        )

        completion = self.llm(messages=llm_messages, **agent_options())
        reply = str(completion.get("content") or "").strip()
        if not reply:
            reply = "OpenRouter/model не вернул видимый текст."

        response_tokens_estimated = count_text_tokens(reply, model)
        response_tokens_actual = completion.get("completion_tokens")
        prompt_tokens_actual = completion.get("prompt_tokens")
        total_tokens_actual = completion.get("total_tokens")
        turn_cost_actual = completion.get("cost")
        turn_cost_estimated = estimate_turn_cost(
            prompt_tokens_actual if prompt_tokens_actual is not None else prompt_tokens_estimated,
            response_tokens_actual if response_tokens_actual is not None else response_tokens_estimated,
            turn_cost_actual,
        )
        tokens_net_saved = (
            prompt_tokens_full_estimated
            - prompt_tokens_estimated
            - summarization_tokens_estimated
        )
        total_tokens_estimated = (
            prompt_tokens_estimated
            + response_tokens_estimated
            + summarization_tokens_estimated
        )

        judge = None
        if run_judge:
            judge = safe_judge_answer(
                self.llm,
                user_message,
                reply,
                COMPARE_GROUND_TRUTH,
                agent_options(),
            )

        turn_number = len(memory.get("turns", [])) + 1
        turn = {
            "turn": turn_number,
            "status": "ok",
            "compression_enabled": enabled,
            "current_request_tokens": current_request_tokens,
            "history_tokens_full": history_tokens_full,
            "history_tokens_sent": history_tokens_sent,
            "history_tokens": history_tokens_sent,
            "prompt_tokens_full_estimated": prompt_tokens_full_estimated,
            "prompt_tokens_estimated": prompt_tokens_estimated,
            "prompt_tokens_actual": prompt_tokens_actual,
            "response_tokens_estimated": response_tokens_estimated,
            "response_tokens_actual": response_tokens_actual,
            "summarization_tokens_estimated": summarization_tokens_estimated,
            "tokens_net_saved": tokens_net_saved,
            "total_tokens_estimated": total_tokens_estimated,
            "total_tokens_actual": total_tokens_actual,
            "turn_cost_actual": turn_cost_actual,
            "turn_cost_estimated": turn_cost_estimated,
            "summarization_events": summarization_events,
            "history_meta": history_meta,
            "model_called": True,
        }
        if judge is not None:
            turn["judge"] = judge

        memory["current_chat"]["messages"].append({"role": "user", "content": user_message})
        memory["current_chat"]["messages"].append({"role": "assistant", "content": reply})
        trim_stored_messages(memory)
        memory["current_chat"]["summary"] = str(memory.get("history_summary") or "")
        memory.setdefault("turns", []).append(turn)
        trim_stored_turns(memory)
        apply_turn_to_cumulative(memory.setdefault("cumulative", empty_cumulative()), turn)
        self.memory_store.save(client_id, memory)

        payload_preview = build_payload_preview(
            build_system_prompt(memory, include_history_summary=False),
            history_messages,
            user_message,
            memory.get("history_summary"),
            enabled,
        )

        result = public_memory(memory)
        result.update({
            "reply": reply,
            "metadata": completion_metadata(completion),
            "last_turn": deepcopy(turn),
            "current_turn": deepcopy(turn),
            "payload_preview": payload_preview,
        })
        if judge is not None:
            result["judge"] = judge
        return result


def normalize_memory(data):
    memory = default_memory()
    if not isinstance(data, dict):
        return memory

    for key in ("created_at", "updated_at", "profile", "current_chat", "archived_chats"):
        if key in data:
            memory[key] = data[key]

    memory["history_summary"] = str(data.get("history_summary") or "")
    memory["turns"] = data.get("turns") if isinstance(data.get("turns"), list) else []
    memory["cumulative"] = normalize_cumulative(data.get("cumulative"))

    compression = data.get("compression")
    if isinstance(compression, dict):
        base = default_compression()
        for key in base:
            if key in compression:
                base[key] = compression[key]
        memory["compression"] = base
    ensure_compression_fields(memory)

    profile = memory.get("profile") if isinstance(memory.get("profile"), dict) else {}
    memory["profile"] = {
        "style": str(profile.get("style") or ""),
        "facts": clean_items(profile.get("facts")),
        "inferences": clean_items(profile.get("inferences")),
    }

    current = memory.get("current_chat") if isinstance(memory.get("current_chat"), dict) else {}
    memory["current_chat"] = {
        "id": str(current.get("id") or new_chat_id()),
        "started_at": str(current.get("started_at") or utc_now()),
        "summary": str(current.get("summary") or ""),
        "messages": clean_messages(current.get("messages"), limit=None),
    }

    archived = memory.get("archived_chats")
    if not isinstance(archived, list):
        archived = []
    memory["archived_chats"] = normalize_archived_chats(archived)
    return memory


def normalize_cumulative(value):
    base = empty_cumulative()
    if not isinstance(value, dict):
        return base
    for key in base:
        if key in value:
            base[key] = value[key]
    return base


def public_memory(memory):
    ensure_compression_fields(memory)
    last_turn = memory.get("turns", [])[-1] if memory.get("turns") else None
    config = compression_config()
    return {
        "messages": deepcopy(memory.get("current_chat", {}).get("messages", [])),
        "profile": deepcopy(memory.get("profile", {})),
        "archived_chats": public_archived_chats(memory.get("archived_chats", [])),
        "history_summary": memory.get("history_summary", ""),
        "compression": deepcopy(memory.get("compression", default_compression())),
        "turns": deepcopy(memory.get("turns", [])),
        "cumulative": deepcopy(memory.get("cumulative", empty_cumulative())),
        "current_turn": deepcopy(last_turn) if last_turn else None,
        "model": model_value(),
        "tokenizer": tokenizer_name(),
        "compression_config": config,
        "pricing": pricing_state(),
    }


def token_summary(result):
    cumulative = result.get("cumulative") or {}
    return {
        "cumulative_prompt_estimated": cumulative.get("prompt_tokens_estimated", 0),
        "cumulative_prompt_full_estimated": cumulative.get("prompt_tokens_full_estimated", 0),
        "cumulative_summarization_estimated": cumulative.get("summarization_tokens_estimated", 0),
        "cumulative_total_estimated": cumulative.get("total_tokens_estimated", 0),
        "cumulative_net_saved": cumulative.get("tokens_net_saved", 0),
        "final_prompt_estimated": (result.get("last_turn") or {}).get("prompt_tokens_estimated", 0),
        "final_prompt_full_estimated": (result.get("last_turn") or {}).get("prompt_tokens_full_estimated", 0),
    }


def public_archived_chats(chats):
    return [
        {
            "id": chat.get("id", ""),
            "started_at": chat.get("started_at", ""),
            "ended_at": chat.get("ended_at", ""),
            "summary": chat.get("summary", ""),
            "message_count": len(chat.get("messages") or []),
        }
        for chat in chats
        if isinstance(chat, dict)
    ]


def build_full_llm_messages(memory, user_message):
    messages = clean_messages(memory["current_chat"]["messages"], limit=None)
    return [
        {"role": "system", "content": build_system_prompt(memory, include_history_summary=False)},
        *messages,
        {"role": "user", "content": user_message},
    ]


def build_system_prompt(memory, include_history_summary=False):
    profile = memory.get("profile", {})
    archived = memory.get("archived_chats", [])[-MAX_ARCHIVED_SUMMARIES:]
    archived_text = "\n".join(
        f"- {item.get('summary', '').strip()}"
        for item in archived
        if item.get("summary")
    )
    facts_text = "\n".join(f"- {item}" for item in profile.get("facts", [])) or "- none"
    inferences_text = "\n".join(f"- {item}" for item in profile.get("inferences", [])) or "- none"
    style = profile.get("style") or "No stable style preference recorded yet."
    summaries = archived_text or "- none"

    base = (
        "You are a helpful chat assistant in a context-compression demo.\n"
        "Keep answers concise unless the user asks for detail.\n"
        "Current user message wins over any summary.\n\n"
        f"Preferred communication style:\n{style}\n\n"
        f"Known user facts:\n{facts_text}\n\n"
        f"Tentative inferences about the user:\n{inferences_text}\n\n"
        f"Previous chat summaries:\n{summaries}"
    )
    if include_history_summary:
        return append_summary_block(base, memory.get("history_summary"))
    return base


def agent_options():
    return {
        "model": model_value(),
        "provider": DEFAULT_PROVIDER,
        "include_reasoning": False,
        "reasoning": REASONING_EXCLUDED,
    }


def apply_turn_to_cumulative(cumulative, turn):
    cumulative["prompt_tokens_estimated"] += int(turn.get("prompt_tokens_estimated") or 0)
    cumulative["prompt_tokens_full_estimated"] += int(turn.get("prompt_tokens_full_estimated") or 0)
    cumulative["response_tokens_estimated"] += int(turn.get("response_tokens_estimated") or 0)
    cumulative["summarization_tokens_estimated"] += int(turn.get("summarization_tokens_estimated") or 0)
    cumulative["total_tokens_estimated"] += int(turn.get("total_tokens_estimated") or 0)
    cumulative["tokens_net_saved"] += int(turn.get("tokens_net_saved") or 0)

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


def archive_current_chat(memory):
    current = memory.get("current_chat", {})
    messages = current.get("messages") or []
    summary = str(memory.get("history_summary") or current.get("summary") or "").strip()
    if messages:
        if not summary:
            summary = fallback_summary(messages)
        memory["archived_chats"].append({
            "id": current.get("id") or new_chat_id(),
            "started_at": current.get("started_at") or utc_now(),
            "ended_at": utc_now(),
            "summary": summary[:MAX_SUMMARY_CHARS],
            "messages": clean_messages(messages, limit=None),
        })

    memory["current_chat"] = {
        "id": new_chat_id(),
        "started_at": utc_now(),
        "summary": "",
        "messages": [],
    }
    reset_compression(memory)


def trim_stored_messages(memory):
    limit = max_stored_messages()
    messages = memory.get("current_chat", {}).get("messages") or []
    if len(messages) <= limit:
        return
    dropped = len(messages) - limit
    memory["current_chat"]["messages"] = messages[-limit:]
    compression = memory.get("compression")
    if isinstance(compression, dict):
        summarized_through = int(compression.get("summarized_through") or 0)
        compression["summarized_through"] = max(0, summarized_through - dropped)


def trim_stored_turns(memory):
    limit = max_stored_turns()
    turns = memory.get("turns") or []
    if len(turns) > limit:
        memory["turns"] = turns[-limit:]


def max_stored_messages():
    return env_int("MAX_STORED_MESSAGES", DEFAULT_MAX_STORED_MESSAGES)


def max_stored_turns():
    return env_int("MAX_STORED_TURNS", DEFAULT_MAX_STORED_TURNS)


def env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def fallback_summary(messages):
    text = " ".join(
        f"{item.get('role')}: {item.get('content')}"
        for item in messages[-6:]
        if isinstance(item, dict)
    )
    return text[:MAX_SUMMARY_CHARS]


def clean_messages(value, limit=None):
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
    if limit is None:
        return messages
    return messages[-limit:]


def normalize_archived_chats(value):
    chats = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()[:MAX_SUMMARY_CHARS]
        messages = clean_messages(item.get("messages"), limit=None)
        if not summary and not messages:
            continue
        if not summary:
            summary = fallback_summary(messages)
        chats.append({
            "id": str(item.get("id") or f"legacy-{index + 1}"),
            "started_at": str(item.get("started_at") or ""),
            "ended_at": str(item.get("ended_at") or ""),
            "summary": summary,
            "messages": messages,
        })
    return chats


def clean_items(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        cleaned.append(text[:500])
        seen.add(key)
        if len(cleaned) >= 24:
            break
    return cleaned


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


def model_value():
    return os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)


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
