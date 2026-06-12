import json
import os
import re

try:
    from token_counter import count_message_tokens, count_text_tokens
except ImportError:
    from .token_counter import count_message_tokens, count_text_tokens


DEFAULT_KEEP_RECENT = 6
DEFAULT_COMPRESS_EVERY = 10
DEFAULT_MAX_SUMMARY_CHARS = 900
SUMMARY_MARKER = "Previous conversation summary:"
PINNED_FACTS_HEADER = "Pinned facts (never omit):"


def compression_config():
    return {
        "keep_recent": env_int("CONTEXT_KEEP_RECENT_MESSAGES", DEFAULT_KEEP_RECENT),
        "compress_every": env_int("CONTEXT_COMPRESS_EVERY", DEFAULT_COMPRESS_EVERY),
        "enabled_default": env_bool("CONTEXT_COMPRESSION_ENABLED", True),
        "max_summary_chars": env_int("MAX_SUMMARY_CHARS", DEFAULT_MAX_SUMMARY_CHARS),
    }


def default_compression():
    config = compression_config()
    return {
        "enabled": config["enabled_default"],
        "summarized_through": 0,
        "updates": [],
        "pinned_facts": [],
    }


def ensure_compression_fields(memory):
    if "history_summary" not in memory:
        memory["history_summary"] = str(memory.get("current_chat", {}).get("summary") or "")
    compression = memory.get("compression")
    if not isinstance(compression, dict):
        memory["compression"] = default_compression()
        return
    compression.setdefault("enabled", compression_config()["enabled_default"])
    compression.setdefault("summarized_through", 0)
    compression.setdefault("updates", [])
    compression.setdefault("pinned_facts", [])


def reset_compression(memory):
    memory["history_summary"] = ""
    memory["compression"] = default_compression()


def compression_enabled(memory, override=None):
    if override is not None:
        return bool(override)
    return bool(memory.get("compression", {}).get("enabled", True))


def chat_messages(memory):
    return memory.get("current_chat", {}).get("messages", [])


def format_batch(messages):
    lines = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "?")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def fallback_summary(messages, max_chars=None):
    max_chars = max_chars or compression_config()["max_summary_chars"]
    text = format_batch(messages[-6:])
    return text[:max_chars]


def build_merge_summary_messages(existing_summary, batch_messages):
    payload = {
        "existing_summary": existing_summary or "",
        "new_messages": format_batch(batch_messages),
        "instructions": (
            "Merge existing_summary and new_messages into one compact plain-text summary. "
            "Preserve codewords, names, numbers, languages, project names, and explicit decisions. "
            "Never drop lines under 'Pinned facts (never omit):'. "
            "No markdown. Maximum 900 characters."
        ),
    }
    return [
        {
            "role": "system",
            "content": (
                "You compress chat history into a short summary. "
                "Return plain text only."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def merge_summary_text(existing_summary, new_summary, max_chars=None):
    """Append-style merge for fallback summarization only."""
    max_chars = max_chars or compression_config()["max_summary_chars"]
    existing_summary = str(existing_summary or "").strip()
    new_summary = str(new_summary or "").strip()
    if existing_summary and new_summary:
        merged = f"{existing_summary}\n{new_summary}"
    else:
        merged = existing_summary or new_summary
    return merged[:max_chars]


def cap_summary(text, max_chars=None):
    max_chars = max_chars or compression_config()["max_summary_chars"]
    return str(text or "").strip()[:max_chars]


def pinned_facts_block(pinned_facts):
    facts = [str(item).strip() for item in (pinned_facts or []) if str(item).strip()]
    if not facts:
        return ""
    lines = "\n".join(f"- {item}" for item in facts)
    return f"{PINNED_FACTS_HEADER}\n{lines}"


def normalize_pinned_fact_line(line):
    line = str(line or "").strip()
    if line.startswith("- "):
        line = line[2:].strip()
    return re.sub(r"\s+", " ", line).casefold()


def strip_pinned_facts_block(text, pinned_facts=None):
    text = str(text or "")
    pinned = {
        normalize_pinned_fact_line(item)
        for item in (pinned_facts or [])
        if str(item).strip()
    }
    lines = text.splitlines()
    kept = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != PINNED_FACTS_HEADER:
            kept.append(lines[index])
            index += 1
            continue

        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                index += 1
                continue
            normalized = normalize_pinned_fact_line(stripped)
            if pinned and normalized in pinned:
                index += 1
                continue
            if not pinned and stripped.startswith("- "):
                index += 1
                continue
            break

    return "\n".join(kept).strip()


def apply_pinned_facts(summary, pinned_facts, max_chars=None):
    max_chars = max_chars or compression_config()["max_summary_chars"]
    block = pinned_facts_block(pinned_facts)
    if not block:
        return cap_summary(summary, max_chars)
    body = strip_pinned_facts_block(summary, pinned_facts)
    if body:
        merged = f"{block}\n\n{body}"
    else:
        merged = block
    return cap_summary(merged, max_chars)


def append_summary_block(system_prompt, history_summary):
    summary = str(history_summary or "").strip()
    if not summary:
        return system_prompt
    return (
        f"{system_prompt.rstrip()}\n\n"
        f"{SUMMARY_MARKER}\n{summary}"
    )


def select_history_messages(memory, enabled):
    messages = chat_messages(memory)
    if not enabled:
        return messages, {
            "compression_enabled": False,
            "summarized_through": 0,
            "messages_sent": len(messages),
            "messages_total": len(messages),
        }

    summarized_through = int(memory.get("compression", {}).get("summarized_through") or 0)
    tail = messages[summarized_through:]
    return tail, {
        "compression_enabled": True,
        "summarized_through": summarized_through,
        "messages_sent": len(tail),
        "messages_total": len(messages),
        "history_summary_chars": len(memory.get("history_summary") or ""),
    }


def maybe_compress_history(memory, llm, model, llm_options):
    ensure_compression_fields(memory)
    if not compression_enabled(memory):
        return []

    config = compression_config()
    messages = chat_messages(memory)
    summarized_through = int(memory.get("compression", {}).get("summarized_through") or 0)
    compressible_end = len(messages) - config["keep_recent"]
    pinned_facts = memory.get("compression", {}).get("pinned_facts") or []
    events = []

    while compressible_end - summarized_through >= config["compress_every"]:
        batch = messages[summarized_through : summarized_through + config["compress_every"]]
        if not batch:
            break

        existing_summary = memory.get("history_summary") or ""
        merge_messages = build_merge_summary_messages(existing_summary, batch)
        summarization_error = None
        merged_text = ""

        try:
            completion = llm(messages=merge_messages, **llm_options)
            merged_text = str(completion.get("content") or "").strip()
            if not merged_text:
                raise ValueError("empty summary from model")
            prompt_tokens = completion.get("prompt_tokens")
            completion_tokens = completion.get("completion_tokens")
            memory["history_summary"] = apply_pinned_facts(
                cap_summary(merged_text),
                pinned_facts,
            )
        except Exception as exc:
            summarization_error = str(exc)
            merged_text = fallback_summary(batch)
            prompt_tokens = count_message_tokens(merge_messages, model)
            completion_tokens = count_text_tokens(merged_text, model)
            memory["history_summary"] = apply_pinned_facts(
                merge_summary_text(existing_summary, merged_text),
                pinned_facts,
            )

        summarized_through += config["compress_every"]
        memory["compression"]["summarized_through"] = summarized_through

        event = {
            "at_message_count": len(messages),
            "batch_size": len(batch),
            "summarized_through": summarized_through,
            "summary_chars": len(memory["history_summary"]),
            "summarization_tokens_estimated": int(prompt_tokens or 0) + int(completion_tokens or 0),
            "summarization_prompt_tokens": prompt_tokens,
            "summarization_completion_tokens": completion_tokens,
            "used_fallback": summarization_error is not None,
        }
        if summarization_error:
            event["summarization_error"] = summarization_error
        memory["compression"]["updates"].append(event)
        events.append(event)

    return events


def build_payload_preview(system_prompt, history_messages, user_message, history_summary, enabled):
    system = append_summary_block(system_prompt, history_summary) if enabled else system_prompt
    payload = [{"role": "system", "content": system}, *history_messages]
    if user_message:
        payload.append({"role": "user", "content": user_message})
    return payload


def env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def parse_summary_from_system(content):
    text = str(content or "")
    marker_index = text.find(SUMMARY_MARKER)
    if marker_index == -1:
        return ""
    return text[marker_index + len(SUMMARY_MARKER) :].strip()
