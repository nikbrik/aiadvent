import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROVIDER = {"allow_fallbacks": False}
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
REASONING_EXCLUDED = {"exclude": True}
MAX_CURRENT_MESSAGES = 40
MAX_ARCHIVED_SUMMARIES = 8
MAX_MEMORY_ITEMS = 24
MAX_SUMMARY_CHARS = 900


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_chat_id():
    return str(uuid.uuid4())


def default_memory():
    return {
        "version": 1,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "demo_progress": 0,
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
        "archived_chats": [],
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

    def set_demo_progress(self, client_id, progress):
        memory = self.memory_store.load(client_id)
        memory["demo_progress"] = normalize_progress(progress)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

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
            "messages": clean_messages(restored.get("messages")),
        }
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def respond(self, client_id, message):
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")

        memory = self.memory_store.load(client_id)
        messages = build_llm_messages(memory, message)
        completion = self.llm(messages=messages, **agent_options())
        reply = str(completion.get("content") or "").strip()
        if not reply:
            reply = "OpenRouter/model не вернул видимый текст."

        memory["current_chat"]["messages"].append({"role": "user", "content": message})
        memory["current_chat"]["messages"].append({"role": "assistant", "content": reply})
        trim_current_chat(memory)

        memory_update_error = None
        try:
            update = self.build_memory_update(memory, message, reply)
            apply_memory_update(memory, update)
        except Exception as exc:
            memory_update_error = str(exc)

        self.memory_store.save(client_id, memory)

        result = {
            "reply": reply,
            "messages": memory["current_chat"]["messages"],
            "profile": memory["profile"],
            "archived_chats": memory["archived_chats"],
            "current_chat_summary": memory["current_chat"].get("summary", ""),
            "demo_progress": normalize_progress(memory.get("demo_progress", 0)),
            "metadata": completion_metadata(completion),
        }
        if memory_update_error:
            result["memory_update_error"] = memory_update_error
        return result

    def build_memory_update(self, memory, user_message, assistant_reply):
        prompt = {
            "existing_profile": memory.get("profile", {}),
            "current_chat_summary": memory.get("current_chat", {}).get("summary", ""),
            "latest_turn": {
                "user": user_message,
                "assistant": assistant_reply,
            },
            "instructions": (
                "Return only valid JSON with keys style, facts, inferences, "
                "current_chat_summary. Facts are explicit user facts. "
                "Inferences are broad persona/behavior conclusions and must be phrased "
                "as tentative conclusions, not certain facts. Keep lists concise."
            ),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You update long-term memory for a personal chat agent. "
                    "Return compact JSON only. No markdown."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        completion = self.llm(messages=messages, **agent_options())
        return parse_json_object(completion.get("content") or "")


def normalize_memory(data):
    memory = default_memory()
    if isinstance(data, dict):
        memory.update({key: data.get(key, memory[key]) for key in memory})

    profile = memory.get("profile") if isinstance(memory.get("profile"), dict) else {}
    memory["profile"] = {
        "style": str(profile.get("style") or ""),
        "facts": clean_items(profile.get("facts")),
        "inferences": clean_items(profile.get("inferences")),
    }
    memory["demo_progress"] = normalize_progress(memory.get("demo_progress", 0))

    current = memory.get("current_chat") if isinstance(memory.get("current_chat"), dict) else {}
    memory["current_chat"] = {
        "id": str(current.get("id") or new_chat_id()),
        "started_at": str(current.get("started_at") or utc_now()),
        "summary": str(current.get("summary") or ""),
        "messages": clean_messages(current.get("messages")),
    }

    archived = memory.get("archived_chats")
    if not isinstance(archived, list):
        archived = []
    memory["archived_chats"] = normalize_archived_chats(archived)
    return memory


def public_memory(memory):
    return {
        "profile": deepcopy(memory.get("profile", {})),
        "messages": deepcopy(memory.get("current_chat", {}).get("messages", [])),
        "current_chat_summary": memory.get("current_chat", {}).get("summary", ""),
        "archived_chats": public_archived_chats(memory.get("archived_chats", [])),
        "demo_progress": normalize_progress(memory.get("demo_progress", 0)),
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


def build_llm_messages(memory, user_message):
    current_messages = memory.get("current_chat", {}).get("messages", [])
    recent_messages = current_messages[-MAX_CURRENT_MESSAGES:]
    return [
        {"role": "system", "content": build_system_prompt(memory)},
        *recent_messages,
        {"role": "user", "content": user_message},
    ]


def build_system_prompt(memory):
    profile = memory.get("profile", {})
    current_summary = (
        memory.get("current_chat", {}).get("summary")
        or "No current chat summary yet."
    )
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

    return (
        "You are a helpful personal AI agent with long-term memory.\n"
        "Use the memory to adapt your answer, but current user message wins over memory.\n"
        "Never present inferences as confirmed facts.\n\n"
        f"Preferred communication style:\n{style}\n\n"
        f"Known user facts:\n{facts_text}\n\n"
        f"Tentative inferences about the user:\n{inferences_text}\n\n"
        f"Current chat summary:\n{current_summary}\n\n"
        f"Previous chat summaries:\n{summaries}"
    )


def agent_options():
    return {
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "include_reasoning": False,
        "reasoning": REASONING_EXCLUDED,
    }


def apply_memory_update(memory, update):
    if not isinstance(update, dict):
        raise ValueError("memory update must be an object")

    profile = memory["profile"]
    if "style" in update:
        profile["style"] = str(update.get("style") or "").strip()[:1200]
    if "facts" in update:
        profile["facts"] = clean_items(update.get("facts"))
    if "inferences" in update:
        profile["inferences"] = clean_items(update.get("inferences"))
    if "current_chat_summary" in update:
        memory["current_chat"]["summary"] = str(update.get("current_chat_summary") or "").strip()[:MAX_SUMMARY_CHARS]


def archive_current_chat(memory):
    current = memory.get("current_chat", {})
    messages = current.get("messages") or []
    summary = str(current.get("summary") or "").strip()
    if messages:
        if not summary:
            summary = fallback_summary(messages)
        memory["archived_chats"].append({
            "id": current.get("id") or new_chat_id(),
            "started_at": current.get("started_at") or utc_now(),
            "ended_at": utc_now(),
            "summary": summary[:MAX_SUMMARY_CHARS],
            "messages": clean_messages(messages),
        })

    memory["current_chat"] = {
        "id": new_chat_id(),
        "started_at": utc_now(),
        "summary": "",
        "messages": [],
    }


def fallback_summary(messages):
    text = " ".join(
        f"{item.get('role')}: {item.get('content')}"
        for item in messages[-6:]
        if isinstance(item, dict)
    )
    return text[:MAX_SUMMARY_CHARS]


def trim_current_chat(memory):
    messages = memory["current_chat"]["messages"]
    if len(messages) > MAX_CURRENT_MESSAGES:
        memory["current_chat"]["messages"] = messages[-MAX_CURRENT_MESSAGES:]


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
    return messages[-MAX_CURRENT_MESSAGES:]


def normalize_archived_chats(value):
    chats = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()[:MAX_SUMMARY_CHARS]
        messages = clean_messages(item.get("messages"))
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


def normalize_progress(value):
    try:
        progress = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, progress)


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
        if len(cleaned) >= MAX_MEMORY_ITEMS:
            break
    return cleaned


def parse_json_object(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("memory update JSON must be an object")
    return data


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
