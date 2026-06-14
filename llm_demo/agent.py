import json
import math
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROVIDER = {"allow_fallbacks": True}
DEFAULT_MODEL = "meta-llama/llama-3-8b-instruct"
DEFAULT_MAX_TOKENS = 700
REASONING_EXCLUDED = {"exclude": True}

DEFAULT_STRATEGY = "sliding_window"
PROFILE_STRATEGY = "profile_summaries"
MAX_STORED_MESSAGES = 120
SLIDING_WINDOW_MESSAGES = 4
STICKY_RECENT_MESSAGES = 4
TOKEN_CUT_BUDGET = 320
MAX_ARCHIVED_SUMMARIES = 8
MAX_MEMORY_ITEMS = 24
MAX_SUMMARY_CHARS = 900
MAX_PROMPT_PREVIEW_CHARS = 12000

STRATEGIES = [
    {
        "id": "sliding_window",
        "name": "Sliding Window",
        "short_name": "Sliding",
        "description": "Only the last N messages are sent to the model.",
        "convenience_score": 7,
    },
    {
        "id": "sticky_facts",
        "name": "Sticky Facts / Key-Value Memory",
        "short_name": "Facts",
        "description": "Important facts are stored as key-value memory plus recent messages.",
        "convenience_score": 8,
    },
    {
        "id": "branching",
        "name": "Branching",
        "short_name": "Branches",
        "description": "A checkpoint can fork into independent branches.",
        "convenience_score": 6,
    },
    {
        "id": PROFILE_STRATEGY,
        "name": "Profile Memory + History Summaries",
        "short_name": "Profile",
        "description": "Profile facts, inferences, style, current summary, and archived summaries.",
        "convenience_score": 8,
    },
    {
        "id": "token_cut",
        "name": "Tokenization and Cut",
        "short_name": "Token Cut",
        "description": "History is cut by an estimated token budget, not by message count.",
        "convenience_score": 7,
    },
    {
        "id": "context_leveling",
        "name": "Context Leveling",
        "short_name": "Levels",
        "description": "Context is organized into goal, constraints, decisions, questions, and recent focus.",
        "convenience_score": 9,
    },
    {
        "id": "conversation_recreation",
        "name": "Conversation Recreation",
        "short_name": "Recreate",
        "description": "A clean prompt is recreated from structured state instead of raw history.",
        "convenience_score": 6,
    },
]

STRATEGY_IDS = [item["id"] for item in STRATEGIES]
STRATEGY_BY_ID = {item["id"]: item for item in STRATEGIES}

EXPECTED_DETAILS = [
    {
        "key": "goal",
        "label": "цель продукта",
        "keywords": ["семейный задачник", "семейных задач", "координировать домашние дела"],
    },
    {
        "key": "audience",
        "label": "аудитория",
        "keywords": ["родители", "дети 7-12", "дети"],
    },
    {
        "key": "deadline",
        "label": "deadline 3 недели",
        "keywords": ["3 недели", "три недели", "21 день"],
    },
    {
        "key": "offline_first",
        "label": "offline-first",
        "keywords": ["offline-first", "офлайн", "без интернета"],
    },
    {
        "key": "budget_no_ml",
        "label": "бюджет без ML",
        "keywords": ["без ml", "без машинного обучения", "не делаем ml"],
    },
    {
        "key": "roles",
        "label": "роли пользователей",
        "keywords": ["родитель", "ребенок", "админ семьи"],
    },
    {
        "key": "mvp",
        "label": "must-have MVP",
        "keywords": ["списки дел", "назначение задач", "дедлайны", "напоминания"],
    },
    {
        "key": "constraints",
        "label": "запреты и ограничения",
        "keywords": ["без чата", "без оплаты", "android", "без регистрации"],
    },
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_chat_id():
    return str(uuid.uuid4())


def default_memory():
    now = utc_now()
    return {
        "version": 2,
        "created_at": now,
        "updated_at": now,
        "active_strategy": DEFAULT_STRATEGY,
        "demo_progress": 0,
        "demo_run": {},
        "comparison_results": [],
        "profile": empty_profile(),
        "current_chat": empty_chat(),
        "archived_chats": [],
        "strategies": {
            strategy_id: default_strategy_state(strategy_id)
            for strategy_id in STRATEGY_IDS
        },
    }


def empty_chat():
    return {
        "id": new_chat_id(),
        "started_at": utc_now(),
        "summary": "",
        "messages": [],
    }


def empty_profile():
    return {
        "style": "",
        "facts": [],
        "inferences": [],
    }


def default_metrics():
    return {
        "calls": 0,
        "main_calls": 0,
        "auxiliary_calls": 0,
        "estimated_prompt_tokens": 0,
        "total_tokens": 0,
        "total_estimated_prompt_tokens": 0,
        "total_cost": 0,
        "total_duration_ms": 0,
        "last_completion": {},
        "last_auxiliary_completion": {},
    }


def default_context_report(strategy_id):
    return {
        "strategy_id": strategy_id,
        "strategy_name": STRATEGY_BY_ID[strategy_id]["name"],
        "context_blocks": [],
        "prompt_preview": "",
        "estimated_prompt_tokens": 0,
        "actual_prompt_tokens": None,
        "actual_total_tokens": None,
        "included_messages": 0,
        "discarded_messages": 0,
        "kept_details": [],
        "lost_details": [item["label"] for item in EXPECTED_DETAILS],
        "notes": "",
    }


def default_strategy_state(strategy_id):
    state = {
        "id": strategy_id,
        "messages": [],
        "last_prompt": [],
        "context_report": default_context_report(strategy_id),
        "metrics": default_metrics(),
    }
    if strategy_id == "sticky_facts":
        state["facts"] = {}
    elif strategy_id == "sliding_window":
        state["total_seen_messages"] = 0
        state["discarded_messages_total"] = 0
    elif strategy_id == "branching":
        state["checkpoint"] = []
        state["active_branch"] = "main"
        state["branches"] = {
            "main": {
                "id": "main",
                "name": "Main",
                "messages": [],
                "created_at": utc_now(),
            }
        }
    elif strategy_id == PROFILE_STRATEGY:
        state["profile"] = empty_profile()
        state["summary"] = ""
        state["archived_summaries"] = []
    elif strategy_id == "context_leveling":
        state["levels"] = {
            "goal": "",
            "audience": "",
            "constraints": [],
            "decisions": [],
            "open_questions": [],
            "recent_focus": "",
        }
    elif strategy_id == "conversation_recreation":
        state["conversation_state"] = {
            "goal": "",
            "audience": "",
            "constraints": [],
            "roles": [],
            "mvp": [],
            "decisions": [],
            "open_questions": [],
            "non_goals": [],
            "last_user_request": "",
        }
    return state


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

    def set_strategy(self, client_id, strategy_id):
        memory = self.memory_store.load(client_id)
        memory["active_strategy"] = normalize_strategy_id(strategy_id)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def reset_demo(self, client_id):
        memory = self.memory_store.load(client_id)
        memory["demo_progress"] = 0
        memory["demo_run"] = {}
        memory["comparison_results"] = []
        memory["current_chat"] = empty_chat()
        memory["archived_chats"] = []
        memory["profile"] = empty_profile()
        memory["strategies"] = {
            strategy_id: default_strategy_state(strategy_id)
            for strategy_id in STRATEGY_IDS
        }
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def reset_strategy(self, client_id, strategy_id=None):
        memory = self.memory_store.load(client_id)
        strategy_id = normalize_strategy_id(strategy_id or memory.get("active_strategy"))
        memory["strategies"][strategy_id] = default_strategy_state(strategy_id)
        if memory.get("active_strategy") == strategy_id:
            memory["current_chat"] = empty_chat()
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def save_comparison_results(self, client_id, results):
        memory = self.memory_store.load(client_id)
        memory["comparison_results"] = list(results or [])
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def save_demo_run(self, client_id, run_state):
        memory = self.memory_store.load(client_id)
        memory["demo_run"] = normalize_demo_run(run_state)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def clear_demo_run(self, client_id):
        memory = self.memory_store.load(client_id)
        memory["demo_run"] = {}
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def set_demo_progress(self, client_id, progress):
        memory = self.memory_store.load(client_id)
        memory["demo_progress"] = normalize_progress(progress)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def start_new_chat(self, client_id):
        memory = self.memory_store.load(client_id)
        archive_current_chat(memory)
        state = active_strategy_state(memory)
        state["messages"] = []
        if memory["active_strategy"] == "branching":
            state["checkpoint"] = []
            state["active_branch"] = "main"
            state["branches"] = default_strategy_state("branching")["branches"]
        if memory["active_strategy"] == PROFILE_STRATEGY:
            archive_profile_state(state)
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
        restored_messages = clean_messages(restored.get("messages"))
        memory["current_chat"] = {
            "id": restored.get("id") or new_chat_id(),
            "started_at": restored.get("started_at") or utc_now(),
            "summary": restored.get("summary", ""),
            "messages": restored_messages,
        }
        state = active_strategy_state(memory)
        set_strategy_messages(state, memory["active_strategy"], restored_messages)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def create_checkpoint(self, client_id):
        memory = self.memory_store.load(client_id)
        state = memory["strategies"]["branching"]
        messages = get_strategy_messages(state, "branching")
        state["checkpoint"] = clean_messages(messages)
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def create_branches(self, client_id):
        memory = self.memory_store.load(client_id)
        state = memory["strategies"]["branching"]
        base = clean_messages(state.get("checkpoint") or get_strategy_messages(state, "branching"))
        state["checkpoint"] = deepcopy(base)
        state["branches"] = {
            "branch_a": {
                "id": "branch_a",
                "name": "Branch A: быстрый MVP",
                "messages": deepcopy(base),
                "created_at": utc_now(),
            },
            "branch_b": {
                "id": "branch_b",
                "name": "Branch B: enterprise",
                "messages": deepcopy(base),
                "created_at": utc_now(),
            },
        }
        state["active_branch"] = "branch_a"
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def switch_branch(self, client_id, branch_id):
        memory = self.memory_store.load(client_id)
        state = memory["strategies"]["branching"]
        branch_id = str(branch_id or "").strip()
        if branch_id not in state.get("branches", {}):
            raise ValueError("branch was not found")
        state["active_branch"] = branch_id
        memory["active_strategy"] = "branching"
        self.memory_store.save(client_id, memory)
        return public_memory(memory)

    def respond(self, client_id, message):
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")

        memory = self.memory_store.load(client_id)
        strategy_id = normalize_strategy_id(memory.get("active_strategy"))
        memory["active_strategy"] = strategy_id
        prepare_strategy_for_user(memory, strategy_id, message)

        messages, report = build_strategy_prompt(memory, strategy_id, message)
        completion = self.llm(messages=messages, **agent_options())
        reply = str(completion.get("content") or "").strip()
        if not reply:
            reply = "OpenRouter/model не вернул видимый текст."

        append_strategy_turn(memory, strategy_id, message, reply)
        append_compat_turn(memory, message, reply)

        metadata = completion_metadata(completion)
        report["actual_prompt_tokens"] = metadata.get("prompt_tokens")
        report["actual_total_tokens"] = metadata.get("total_tokens")
        report["kept_details"], report["lost_details"] = score_details(prompt_to_text(messages))

        state = memory["strategies"][strategy_id]
        state["last_prompt"] = deepcopy(messages)
        state["context_report"] = report
        update_metrics(state, report, metadata)

        memory_update_error = None
        try:
            update_strategy_after_reply(self, memory, strategy_id, message, reply)
        except Exception as exc:
            memory_update_error = str(exc)

        self.memory_store.save(client_id, memory)

        result = public_memory(memory)
        result["reply"] = reply
        result["metadata"] = metadata
        if memory_update_error:
            result["memory_update_error"] = memory_update_error
        return result

    def build_profile_memory_update(self, profile_state, user_message, assistant_reply):
        prompt = {
            "existing_profile": profile_state.get("profile", {}),
            "current_chat_summary": profile_state.get("summary", ""),
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
        return {
            "content": completion.get("content") or "",
            "messages": messages,
            "metadata": completion_metadata(completion),
        }


def normalize_memory(data):
    memory = default_memory()
    old_schema = memory_schema_version(data) < 2
    if isinstance(data, dict):
        memory["version"] = 2
        memory["created_at"] = str(data.get("created_at") or memory["created_at"])
        memory["updated_at"] = str(data.get("updated_at") or memory["updated_at"])
        memory["active_strategy"] = normalize_strategy_id(
            data.get("active_strategy") or (PROFILE_STRATEGY if old_schema else DEFAULT_STRATEGY)
        )
        memory["demo_progress"] = normalize_progress(data.get("demo_progress", 0))
        if isinstance(data.get("demo_run"), dict):
            memory["demo_run"] = normalize_demo_run(data["demo_run"])
        if isinstance(data.get("comparison_results"), list):
            memory["comparison_results"] = data["comparison_results"]

        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        memory["profile"] = normalize_profile(profile)

        current = data.get("current_chat") if isinstance(data.get("current_chat"), dict) else {}
        memory["current_chat"] = normalize_chat(current)

        archived = data.get("archived_chats")
        memory["archived_chats"] = normalize_archived_chats(archived if isinstance(archived, list) else [])

        raw_strategies = data.get("strategies")
        if not isinstance(raw_strategies, dict):
            raw_strategies = data.get("strategy_states") if isinstance(data.get("strategy_states"), dict) else {}
        memory["strategies"] = normalize_strategies(raw_strategies)

    if old_schema:
        seed_profile_strategy(memory)
    return memory


def normalize_strategies(raw_strategies):
    strategies = {}
    for strategy_id in STRATEGY_IDS:
        strategies[strategy_id] = normalize_strategy_state(
            strategy_id,
            raw_strategies.get(strategy_id) if isinstance(raw_strategies, dict) else {},
        )
    return strategies


def normalize_strategy_state(strategy_id, raw_state):
    state = default_strategy_state(strategy_id)
    if not isinstance(raw_state, dict):
        return state

    raw_messages = clean_messages(raw_state.get("messages"))
    message_limit = strategy_message_limit(strategy_id)
    state["messages"] = clean_messages(raw_messages, limit=message_limit)
    state["last_prompt"] = clean_messages(raw_state.get("last_prompt"))
    if isinstance(raw_state.get("context_report"), dict):
        report = default_context_report(strategy_id)
        report.update({
            key: raw_state["context_report"].get(key, report[key])
            for key in report
        })
        state["context_report"] = report
    if isinstance(raw_state.get("metrics"), dict):
        metrics = default_metrics()
        metrics.update({
            key: raw_state["metrics"].get(key, metrics[key])
            for key in metrics
        })
        state["metrics"] = metrics

    if strategy_id == "sliding_window":
        total = int(raw_state.get("total_seen_messages") or len(raw_messages))
        total = max(total, len(state["messages"]))
        discarded = int(raw_state.get("discarded_messages_total") or max(0, total - len(state["messages"])))
        state["total_seen_messages"] = total
        state["discarded_messages_total"] = max(discarded, total - len(state["messages"]))
    elif strategy_id == "sticky_facts":
        facts = raw_state.get("facts")
        state["facts"] = normalize_fact_dict(facts)
    elif strategy_id == "branching":
        state["checkpoint"] = clean_messages(raw_state.get("checkpoint"))
        branches = raw_state.get("branches")
        if isinstance(branches, dict) and branches:
            state["branches"] = {}
            for branch_id, branch in branches.items():
                if not isinstance(branch, dict):
                    continue
                branch_id = str(branch.get("id") or branch_id)
                state["branches"][branch_id] = {
                    "id": branch_id,
                    "name": str(branch.get("name") or branch_id),
                    "messages": clean_messages(branch.get("messages")),
                    "created_at": str(branch.get("created_at") or ""),
                }
        if not state["branches"]:
            state["branches"] = default_strategy_state("branching")["branches"]
        active = str(raw_state.get("active_branch") or "main")
        state["active_branch"] = active if active in state["branches"] else next(iter(state["branches"]))
    elif strategy_id == PROFILE_STRATEGY:
        state["profile"] = normalize_profile(raw_state.get("profile") if isinstance(raw_state.get("profile"), dict) else {})
        state["summary"] = str(raw_state.get("summary") or "")[:MAX_SUMMARY_CHARS]
        state["archived_summaries"] = clean_items(raw_state.get("archived_summaries"))
    elif strategy_id == "context_leveling":
        levels = raw_state.get("levels") if isinstance(raw_state.get("levels"), dict) else {}
        state["levels"] = {
            "goal": str(levels.get("goal") or ""),
            "audience": str(levels.get("audience") or ""),
            "constraints": clean_items(levels.get("constraints")),
            "decisions": clean_items(levels.get("decisions")),
            "open_questions": clean_items(levels.get("open_questions")),
            "recent_focus": str(levels.get("recent_focus") or ""),
        }
    elif strategy_id == "conversation_recreation":
        raw = raw_state.get("conversation_state") if isinstance(raw_state.get("conversation_state"), dict) else {}
        current = state["conversation_state"]
        for key, value in raw.items():
            if key in current and isinstance(current[key], list):
                current[key] = clean_items(value)
            elif key in current:
                current[key] = str(value or "")
    return state


def seed_profile_strategy(memory):
    profile_state = memory["strategies"][PROFILE_STRATEGY]
    profile_state["profile"] = deepcopy(memory["profile"])
    profile_state["summary"] = memory["current_chat"].get("summary", "")
    profile_state["messages"] = clean_messages(memory["current_chat"].get("messages"))
    profile_state["archived_summaries"] = [
        item.get("summary", "")
        for item in memory.get("archived_chats", [])[-MAX_ARCHIVED_SUMMARIES:]
        if item.get("summary")
    ]


def public_memory(memory):
    strategy_id = normalize_strategy_id(memory.get("active_strategy"))
    state = memory["strategies"][strategy_id]
    messages = get_strategy_messages(state, strategy_id)
    profile_state = memory["strategies"][PROFILE_STRATEGY]
    comparison = memory.get("comparison_results") if isinstance(memory.get("comparison_results"), list) else []
    return {
        "active_strategy": strategy_id,
        "strategies": public_strategies(memory),
        "messages": deepcopy(messages),
        "strategy_state": public_strategy_state(state, strategy_id),
        "context_report": deepcopy(state.get("context_report", default_context_report(strategy_id))),
        "comparison_results": deepcopy(comparison),
        "profile": deepcopy(profile_state.get("profile", memory.get("profile", {}))),
        "current_chat_summary": profile_state.get("summary", memory.get("current_chat", {}).get("summary", "")),
        "archived_chats": public_archived_chats(memory.get("archived_chats", [])),
        "demo_progress": normalize_progress(memory.get("demo_progress", 0)),
        "demo_run": deepcopy(memory.get("demo_run", {})),
    }


def public_strategies(memory):
    values = []
    for item in STRATEGIES:
        state = memory["strategies"][item["id"]]
        metrics = state.get("metrics", {})
        report = state.get("context_report", {})
        messages = get_strategy_messages(state, item["id"])
        values.append({
            **item,
            "active": item["id"] == memory.get("active_strategy"),
            "message_count": len(messages),
            "estimated_prompt_tokens": report.get("estimated_prompt_tokens", 0),
            "total_tokens": metrics.get("total_tokens", 0),
            "calls": metrics.get("calls", 0),
        })
    return values


def public_strategy_state(state, strategy_id):
    data = {
        "id": strategy_id,
        "messages": deepcopy(get_strategy_messages(state, strategy_id)),
        "metrics": deepcopy(state.get("metrics", default_metrics())),
    }
    if strategy_id == "sliding_window":
        data["total_seen_messages"] = int(state.get("total_seen_messages") or len(data["messages"]))
        data["discarded_messages_total"] = int(state.get("discarded_messages_total") or 0)
    elif strategy_id == "sticky_facts":
        data["facts"] = deepcopy(state.get("facts", {}))
    elif strategy_id == "branching":
        data["checkpoint_message_count"] = len(state.get("checkpoint") or [])
        data["active_branch"] = state.get("active_branch", "main")
        data["branches"] = [
            {
                "id": branch.get("id", ""),
                "name": branch.get("name", ""),
                "message_count": len(branch.get("messages") or []),
                "final_answer": last_assistant_message(branch.get("messages") or []),
                "active": branch.get("id") == state.get("active_branch"),
            }
            for branch in state.get("branches", {}).values()
        ]
    elif strategy_id == PROFILE_STRATEGY:
        data["profile"] = deepcopy(state.get("profile", empty_profile()))
        data["summary"] = state.get("summary", "")
        data["archived_summaries"] = deepcopy(state.get("archived_summaries", []))
    elif strategy_id == "context_leveling":
        data["levels"] = deepcopy(state.get("levels", {}))
    elif strategy_id == "conversation_recreation":
        data["conversation_state"] = deepcopy(state.get("conversation_state", {}))
    return data


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


def active_strategy_state(memory):
    strategy_id = normalize_strategy_id(memory.get("active_strategy"))
    return memory["strategies"][strategy_id]


def normalize_strategy_id(value):
    strategy_id = str(value or DEFAULT_STRATEGY).strip()
    if strategy_id not in STRATEGY_BY_ID:
        raise ValueError("unknown context strategy")
    return strategy_id


def build_strategy_prompt(memory, strategy_id, user_message):
    state = memory["strategies"][strategy_id]
    builders = {
        "sliding_window": build_sliding_prompt,
        "sticky_facts": build_sticky_prompt,
        "branching": build_branching_prompt,
        PROFILE_STRATEGY: build_profile_prompt,
        "token_cut": build_token_cut_prompt,
        "context_leveling": build_context_leveling_prompt,
        "conversation_recreation": build_recreation_prompt,
    }
    messages, report = builders[strategy_id](state, user_message)
    report["strategy_id"] = strategy_id
    report["strategy_name"] = STRATEGY_BY_ID[strategy_id]["name"]
    report["prompt_preview"] = prompt_to_text(messages)[:MAX_PROMPT_PREVIEW_CHARS]
    report["estimated_prompt_tokens"] = estimate_tokens_for_messages(messages)
    return messages, report


def base_system_prompt(title):
    return (
        f"You are a Russian-speaking AI agent demoing context strategy: {title}.\n"
        "Help collect a product requirements document. Be concrete and do not invent details.\n"
        "If context is missing, say what is missing."
    )


def build_sliding_prompt(state, user_message):
    history = state.get("messages", [])
    recent = history[-SLIDING_WINDOW_MESSAGES:]
    discarded = int(
        state.get("discarded_messages_total")
        or max(0, int(state.get("total_seen_messages") or len(history)) - len(recent))
    )
    messages = [
        {"role": "system", "content": base_system_prompt("Sliding Window")},
        *deepcopy(recent),
        {"role": "user", "content": user_message},
    ]
    return messages, make_report(
        "sliding_window",
        ["System instructions", f"Last {SLIDING_WINDOW_MESSAGES} messages"],
        len(recent),
        discarded,
        "Only the tail of the transcript is visible; older messages are physically dropped.",
    )


def build_sticky_prompt(state, user_message):
    facts = state.get("facts", {})
    facts_text = json.dumps(facts, ensure_ascii=False, indent=2) if facts else "{}"
    history = state.get("messages", [])
    recent = history[-STICKY_RECENT_MESSAGES:]
    messages = [
        {
            "role": "system",
            "content": (
                base_system_prompt("Sticky Facts / Key-Value Memory")
                + "\n\nSticky facts JSON:\n"
                + facts_text
            ),
        },
        *deepcopy(recent),
        {"role": "user", "content": user_message},
    ]
    return messages, make_report(
        "sticky_facts",
        ["System instructions", "Sticky key-value facts", f"Last {STICKY_RECENT_MESSAGES} messages"],
        len(recent),
        max(0, len(history) - len(recent)),
        "Facts are retained outside the transcript tail.",
    )


def build_branching_prompt(state, user_message):
    branch = active_branch(state)
    history = branch.get("messages", [])
    messages = [
        {
            "role": "system",
            "content": (
                base_system_prompt("Branching")
                + f"\n\nActive branch: {branch.get('name', branch.get('id', 'branch'))}.\n"
                "Use only this branch transcript."
            ),
        },
        *deepcopy(history),
        {"role": "user", "content": user_message},
    ]
    other_count = sum(
        len(item.get("messages") or [])
        for branch_id, item in state.get("branches", {}).items()
        if branch_id != state.get("active_branch")
    )
    return messages, make_report(
        "branching",
        ["System instructions", "Active branch transcript"],
        len(history),
        other_count,
        "Other branches are intentionally hidden.",
    )


def build_profile_prompt(state, user_message):
    profile = state.get("profile", empty_profile())
    facts_text = "\n".join(f"- {item}" for item in profile.get("facts", [])) or "- none"
    inferences_text = "\n".join(f"- {item}" for item in profile.get("inferences", [])) or "- none"
    style = profile.get("style") or "No stable style preference recorded yet."
    summaries = "\n".join(f"- {item}" for item in state.get("archived_summaries", [])) or "- none"
    current_summary = state.get("summary") or "No current chat summary yet."
    history = state.get("messages", [])
    recent = history[-SLIDING_WINDOW_MESSAGES:]
    system = (
        base_system_prompt("Profile Memory + History Summaries")
        + "\n\nPreferred communication style:\n"
        + style
        + "\n\nKnown user facts:\n"
        + facts_text
        + "\n\nTentative inferences about the user:\n"
        + inferences_text
        + "\n\nCurrent chat summary:\n"
        + current_summary
        + "\n\nPrevious chat summaries:\n"
        + summaries
    )
    messages = [
        {"role": "system", "content": system},
        *deepcopy(recent),
        {"role": "user", "content": user_message},
    ]
    return messages, make_report(
        PROFILE_STRATEGY,
        ["System instructions", "Profile", "Current summary", "Archived summaries", "Recent messages"],
        len(recent),
        max(0, len(history) - len(recent)),
        "This is the existing rich memory strategy preserved as a separate mode.",
    )


def build_token_cut_prompt(state, user_message):
    history = state.get("messages", [])
    system = {"role": "system", "content": base_system_prompt("Tokenization and Cut")}
    user = {"role": "user", "content": user_message}
    selected = []
    truncated = 0
    token_count = estimate_tokens_for_messages([system, user])
    for item in reversed(history):
        item_tokens = estimate_tokens_for_messages([item])
        if token_count + item_tokens > TOKEN_CUT_BUDGET:
            truncated_item = truncate_message_to_budget(item, TOKEN_CUT_BUDGET - token_count)
            if truncated_item:
                selected.append(truncated_item)
                token_count += estimate_tokens_for_messages([truncated_item])
                truncated += 1
            break
        selected.append(item)
        token_count += item_tokens
    selected.reverse()
    messages = [system, *deepcopy(selected), user]
    blocks = ["System instructions", f"History cut to ~{TOKEN_CUT_BUDGET} tokens"]
    if truncated:
        blocks.append("Oversized history message truncated")
    report = make_report(
        "token_cut",
        blocks,
        len(selected),
        max(0, len(history) - len(selected)),
        "History is selected by estimated token budget; oversized history messages are cut.",
    )
    report["truncated_messages"] = truncated
    return messages, report


def build_context_leveling_prompt(state, user_message):
    levels = state.get("levels", {})
    levels_text = (
        f"Goal: {levels.get('goal') or 'unknown'}\n"
        f"Audience: {levels.get('audience') or 'unknown'}\n"
        f"Constraints:\n{format_list(levels.get('constraints'))}\n"
        f"Decisions:\n{format_list(levels.get('decisions'))}\n"
        f"Open questions:\n{format_list(levels.get('open_questions'))}\n"
        f"Recent focus: {levels.get('recent_focus') or 'unknown'}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                base_system_prompt("Context Leveling")
                + "\n\nContext levels, highest priority first:\n"
                + levels_text
            ),
        },
        {"role": "user", "content": user_message},
    ]
    return messages, make_report(
        "context_leveling",
        ["System instructions", "Goal", "Audience", "Constraints", "Decisions", "Open questions", "Current message"],
        1,
        len(state.get("messages", [])),
        "Raw history is hidden; structured levels define the context.",
    )


def build_recreation_prompt(state, user_message):
    conversation_state = state.get("conversation_state", {})
    state_text = json.dumps(conversation_state, ensure_ascii=False, indent=2)
    messages = [
        {
            "role": "system",
            "content": (
                base_system_prompt("Conversation Recreation")
                + "\n\nRecreated conversation state:\n"
                + state_text
                + "\n\nContinue from this clean state, not from raw transcript."
            ),
        },
        {"role": "user", "content": user_message},
    ]
    return messages, make_report(
        "conversation_recreation",
        ["System instructions", "Recreated structured state", "Current message"],
        1,
        len(state.get("messages", [])),
        "Prompt is recreated from state and current input only.",
    )


def make_report(strategy_id, blocks, included, discarded, notes):
    report = default_context_report(strategy_id)
    report["context_blocks"] = blocks
    report["included_messages"] = included
    report["discarded_messages"] = discarded
    report["notes"] = notes
    return report


def prepare_strategy_for_user(memory, strategy_id, user_message):
    state = memory["strategies"][strategy_id]
    if strategy_id == "sticky_facts":
        state["facts"].update(extract_fact_dict(user_message))
    elif strategy_id == "context_leveling":
        update_context_levels(state["levels"], user_message)
    elif strategy_id == "conversation_recreation":
        update_recreation_state(state["conversation_state"], user_message)


def update_strategy_after_reply(agent, memory, strategy_id, user_message, assistant_reply):
    if strategy_id != PROFILE_STRATEGY:
        return
    state = memory["strategies"][PROFILE_STRATEGY]
    update_payload = agent.build_profile_memory_update(state, user_message, assistant_reply)
    update_auxiliary_metrics(state, update_payload.get("messages", []), update_payload.get("metadata", {}))
    update = parse_json_object(update_payload.get("content") or "")
    apply_profile_update(state, update)
    memory["profile"] = deepcopy(state["profile"])
    memory["current_chat"]["summary"] = state.get("summary", "")


def append_strategy_turn(memory, strategy_id, user_message, assistant_reply):
    state = memory["strategies"][strategy_id]
    turn = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_reply},
    ]
    if strategy_id == "branching":
        branch = active_branch(state)
        branch["messages"].extend(turn)
        branch["messages"] = clean_messages(branch["messages"])
        state["messages"] = clean_messages(branch["messages"])
    else:
        if strategy_id == "sliding_window":
            state["total_seen_messages"] = int(state.get("total_seen_messages") or 0) + len(turn)
        state["messages"].extend(turn)
        limit = strategy_message_limit(strategy_id)
        overflow = max(0, len(state["messages"]) - limit)
        if strategy_id == "sliding_window" and overflow:
            state["discarded_messages_total"] = int(state.get("discarded_messages_total") or 0) + overflow
        state["messages"] = clean_messages(state["messages"], limit=limit)


def append_compat_turn(memory, user_message, assistant_reply):
    memory["current_chat"]["messages"].append({"role": "user", "content": user_message})
    memory["current_chat"]["messages"].append({"role": "assistant", "content": assistant_reply})
    memory["current_chat"]["messages"] = clean_messages(memory["current_chat"]["messages"])


def active_branch(state):
    branches = state.get("branches") or {}
    if not branches:
        state["branches"] = default_strategy_state("branching")["branches"]
        branches = state["branches"]
    active = state.get("active_branch") or "main"
    if active not in branches:
        active = next(iter(branches))
        state["active_branch"] = active
    return branches[active]


def get_strategy_messages(state, strategy_id):
    if strategy_id == "branching":
        return deepcopy(active_branch(state).get("messages", []))
    return deepcopy(state.get("messages", []))


def set_strategy_messages(state, strategy_id, messages):
    if strategy_id == "branching":
        branch = active_branch(state)
        branch["messages"] = clean_messages(messages)
        state["messages"] = clean_messages(messages)
    else:
        state["messages"] = clean_messages(messages, limit=strategy_message_limit(strategy_id))


def update_metrics(state, report, metadata):
    metrics = state.setdefault("metrics", default_metrics())
    metrics["calls"] = int(metrics.get("calls") or 0) + 1
    metrics["main_calls"] = int(metrics.get("main_calls") or 0) + 1
    estimate = int(report.get("estimated_prompt_tokens") or 0)
    metrics["estimated_prompt_tokens"] = estimate
    metrics["total_estimated_prompt_tokens"] = int(metrics.get("total_estimated_prompt_tokens") or 0) + estimate
    metrics["total_tokens"] = int(metrics.get("total_tokens") or 0) + int(metadata.get("total_tokens") or 0)
    metrics["total_cost"] = float(metrics.get("total_cost") or 0) + float(metadata.get("cost") or 0)
    metrics["total_duration_ms"] = int(metrics.get("total_duration_ms") or 0) + int(metadata.get("duration_ms") or 0)
    metrics["last_completion"] = deepcopy(metadata)


def update_auxiliary_metrics(state, messages, metadata):
    metrics = state.setdefault("metrics", default_metrics())
    metrics["calls"] = int(metrics.get("calls") or 0) + 1
    metrics["auxiliary_calls"] = int(metrics.get("auxiliary_calls") or 0) + 1
    estimate = estimate_tokens_for_messages(messages)
    metrics["total_estimated_prompt_tokens"] = int(metrics.get("total_estimated_prompt_tokens") or 0) + estimate
    metrics["total_tokens"] = int(metrics.get("total_tokens") or 0) + int(metadata.get("total_tokens") or 0)
    metrics["total_cost"] = float(metrics.get("total_cost") or 0) + float(metadata.get("cost") or 0)
    metrics["total_duration_ms"] = int(metrics.get("total_duration_ms") or 0) + int(metadata.get("duration_ms") or 0)
    metrics["last_auxiliary_completion"] = deepcopy(metadata)


def apply_profile_update(state, update):
    if not isinstance(update, dict):
        raise ValueError("memory update must be an object")

    profile = state["profile"]
    if "style" in update:
        profile["style"] = str(update.get("style") or "").strip()[:1200]
    if "facts" in update:
        profile["facts"] = clean_items(update.get("facts"))
    if "inferences" in update:
        profile["inferences"] = clean_items(update.get("inferences"))
    if "current_chat_summary" in update:
        state["summary"] = str(update.get("current_chat_summary") or "").strip()[:MAX_SUMMARY_CHARS]


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

    memory["current_chat"] = empty_chat()


def archive_profile_state(state):
    summary = str(state.get("summary") or "").strip()
    if not summary and state.get("messages"):
        summary = fallback_summary(state["messages"])
    if summary:
        summaries = state.setdefault("archived_summaries", [])
        summaries.append(summary[:MAX_SUMMARY_CHARS])
        state["archived_summaries"] = summaries[-MAX_ARCHIVED_SUMMARIES:]
    state["summary"] = ""
    state["messages"] = []


def fallback_summary(messages):
    text = " ".join(
        f"{item.get('role')}: {item.get('content')}"
        for item in messages[-6:]
        if isinstance(item, dict)
    )
    return text[:MAX_SUMMARY_CHARS]


def extract_fact_dict(text):
    facts = {}
    lower = text.lower()
    if any(word in lower for word in ["цель", "семейный задачник", "семейных задач"]):
        facts["goal"] = "семейный задачник для координации домашних дел"
    if any(word in lower for word in ["родители", "дети", "7-12"]):
        facts["audience"] = "родители и дети 7-12 лет"
    if any(word in lower for word in ["3 недели", "три недели", "deadline", "дедлайн"]):
        facts["deadline"] = "MVP за 3 недели"
    if any(word in lower for word in ["offline-first", "офлайн", "без интернета"]):
        facts["offline_first"] = "работает offline-first"
    if any(word in lower for word in ["без ml", "машинного обучения", "не делаем ml"]):
        facts["budget"] = "бюджет без ML и машинного обучения"
    if any(word in lower for word in ["родитель", "ребенок", "админ семьи"]):
        facts["roles"] = "родитель, ребенок, админ семьи"
    if any(word in lower for word in ["списки дел", "назначение задач", "дедлайны", "напоминания"]):
        facts["mvp"] = "списки дел, назначение задач, дедлайны, напоминания"
    if any(word in lower for word in ["без чата", "без оплаты", "android", "без регистрации"]):
        facts["constraints"] = "Android-first, без чата, оплаты и лишней регистрации"
    return facts


def update_context_levels(levels, text):
    facts = extract_fact_dict(text)
    if "goal" in facts:
        levels["goal"] = facts["goal"]
    if "audience" in facts:
        levels["audience"] = facts["audience"]
    append_unique_from_keys(levels["constraints"], facts, ["deadline", "offline_first", "budget", "constraints"])
    append_unique_from_keys(levels["decisions"], facts, ["roles", "mvp"])
    lower = text.lower()
    if any(word in lower for word in ["вопрос", "неясно", "открыто", "под вопросом"]):
        append_unique(levels["open_questions"], compact_sentence(text))
    if any(word in lower for word in ["решили", "фиксируем", "выбираем", "оставляем"]):
        append_unique(levels["decisions"], compact_sentence(text))
    levels["recent_focus"] = compact_sentence(text)


def update_recreation_state(state, text):
    facts = extract_fact_dict(text)
    if "goal" in facts:
        state["goal"] = facts["goal"]
    if "audience" in facts:
        state["audience"] = facts["audience"]
    append_unique_from_keys(state["constraints"], facts, ["deadline", "offline_first", "budget", "constraints"])
    append_unique_from_keys(state["roles"], facts, ["roles"])
    append_unique_from_keys(state["mvp"], facts, ["mvp"])
    lower = text.lower()
    if any(word in lower for word in ["без чата", "без оплаты", "без ml", "не делаем"]):
        append_unique(state["non_goals"], compact_sentence(text))
    if any(word in lower for word in ["решили", "фиксируем", "выбираем", "оставляем"]):
        append_unique(state["decisions"], compact_sentence(text))
    if any(word in lower for word in ["вопрос", "неясно", "открыто", "под вопросом"]):
        append_unique(state["open_questions"], compact_sentence(text))
    state["last_user_request"] = compact_sentence(text)


def append_unique_from_keys(target, facts, keys):
    for key in keys:
        if key in facts:
            append_unique(target, facts[key])


def append_unique(target, value):
    value = str(value or "").strip()
    if not value:
        return
    key = value.lower()
    if key not in {item.lower() for item in target}:
        target.append(value[:500])
    del target[MAX_MEMORY_ITEMS:]


def compact_sentence(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:240]


def last_assistant_message(messages):
    return next(
        (
            item.get("content", "")
            for item in reversed(messages or [])
            if isinstance(item, dict) and item.get("role") == "assistant"
        ),
        "",
    )


def truncate_message_to_budget(message, token_budget):
    token_budget = int(token_budget or 0)
    if token_budget <= 12 or not isinstance(message, dict):
        return None
    role = message.get("role")
    content = str(message.get("content") or "")
    if role not in ("user", "assistant") or not content:
        return None
    marker = "\n\n[truncated by token budget]"
    max_chars = max(0, (token_budget - 8) * 4)
    if max_chars <= len(marker) + 40:
        return None
    if len(content) <= max_chars:
        return deepcopy(message)
    return {
        "role": role,
        "content": content[: max_chars - len(marker)] + marker,
    }


def score_details(text):
    lower = str(text or "").lower()
    kept = []
    lost = []
    for detail in EXPECTED_DETAILS:
        if any(keyword in lower for keyword in detail["keywords"]):
            kept.append(detail["label"])
        else:
            lost.append(detail["label"])
    return kept, lost


def comparison_result_for(strategy_public):
    report = strategy_public.get("context_report") or {}
    state = strategy_public.get("strategy_state") or {}
    metrics = state.get("metrics") or {}
    messages = strategy_public.get("messages") or []
    branch_results = []
    if strategy_public.get("active_strategy") == "branching":
        for branch in state.get("branches") or []:
            final_answer = branch.get("final_answer", "")
            branch_kept, branch_lost = score_details(final_answer)
            branch_results.append({
                "id": branch.get("id", ""),
                "name": branch.get("name", ""),
                "final_answer": final_answer,
                "retained_details": branch_kept,
                "lost_details": branch_lost,
                "retained_score": round(10 * len(branch_kept) / max(1, len(EXPECTED_DETAILS)), 1),
            })
    if branch_results:
        final_reply = "\n\n".join(
            f"{item['name']}: {item['final_answer']}"
            for item in branch_results
            if item.get("final_answer")
        )
        kept = sorted({detail for item in branch_results for detail in item["retained_details"]})
        lost = sorted({detail for item in branch_results for detail in item["lost_details"]})
        retained_score = round(
            sum(item["retained_score"] for item in branch_results) / max(1, len(branch_results)),
            1,
        )
    else:
        final_reply = last_assistant_message(messages)
        kept, lost = score_details(final_reply)
        total_expected = max(1, len(EXPECTED_DETAILS))
        retained_score = round(10 * len(kept) / total_expected, 1)
    return {
        "strategy_id": strategy_public.get("active_strategy"),
        "strategy_name": STRATEGY_BY_ID[strategy_public.get("active_strategy")]["name"],
        "final_answer": final_reply,
        "branch_results": branch_results,
        "retained_details": kept,
        "lost_details": lost,
        "retained_score": retained_score,
        "prompt_kept_details": report.get("kept_details", []),
        "prompt_lost_details": report.get("lost_details", []),
        "total_tokens": metrics.get("total_tokens", 0),
        "estimated_prompt_tokens": metrics.get("total_estimated_prompt_tokens", 0),
        "cost": metrics.get("total_cost", 0),
        "duration_ms": metrics.get("total_duration_ms", 0),
        "convenience_score": STRATEGY_BY_ID[strategy_public.get("active_strategy")]["convenience_score"],
        "ux_note": STRATEGY_BY_ID[strategy_public.get("active_strategy")]["description"],
    }


def normalize_profile(profile):
    return {
        "style": str(profile.get("style") or ""),
        "facts": clean_items(profile.get("facts")),
        "inferences": clean_items(profile.get("inferences")),
    }


def normalize_chat(current):
    return {
        "id": str(current.get("id") or new_chat_id()),
        "started_at": str(current.get("started_at") or utc_now()),
        "summary": str(current.get("summary") or ""),
        "messages": clean_messages(current.get("messages")),
    }


def normalize_fact_dict(value):
    if not isinstance(value, dict):
        return {}
    facts = {}
    for key, item in value.items():
        clean_key = re.sub(r"[^a-zA-Z0-9_-]", "_", str(key or "").strip().lower())
        text = str(item or "").strip()
        if clean_key and text:
            facts[clean_key] = text[:500]
    return facts


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
            "id": str(item.get("id") or f"archived-{index + 1}"),
            "started_at": str(item.get("started_at") or ""),
            "ended_at": str(item.get("ended_at") or ""),
            "summary": summary,
            "messages": messages,
        })
    return chats


def normalize_demo_run(value):
    if not isinstance(value, dict):
        return {}
    mode = str(value.get("mode") or "").strip()
    if mode not in ("active", "all"):
        return {}
    strategy_id = str(value.get("strategy_id") or "").strip()
    if strategy_id and strategy_id not in STRATEGY_BY_ID:
        strategy_id = ""
    try:
        strategy_index = int(value.get("strategy_index") or 0)
    except (TypeError, ValueError):
        strategy_index = 0
    return {
        "mode": mode,
        "strategy_id": strategy_id,
        "strategy_index": max(0, min(strategy_index, len(STRATEGY_IDS) - 1)),
        "progress": min(normalize_progress(value.get("progress", 0)), 12),
        "results": list(value.get("results") or []) if isinstance(value.get("results"), list) else [],
        "error": str(value.get("error") or ""),
        "updated_at": str(value.get("updated_at") or utc_now()),
    }


def memory_schema_version(data):
    if not isinstance(data, dict):
        return 0
    try:
        return int(data.get("version") or 1)
    except (TypeError, ValueError):
        return 1


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


def clean_messages(value, limit=MAX_STORED_MESSAGES):
    if not isinstance(value, list):
        return []
    messages = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant", "system") and content:
            messages.append({"role": role, "content": content})
    return messages[-limit:]


def strategy_message_limit(strategy_id):
    return SLIDING_WINDOW_MESSAGES if strategy_id == "sliding_window" else MAX_STORED_MESSAGES


def format_list(items):
    values = clean_items(items)
    if not values:
        return "- none"
    return "\n".join(f"- {item}" for item in values)


def prompt_to_text(messages):
    return "\n\n".join(
        f"{item.get('role', '').upper()}:\n{item.get('content', '')}"
        for item in messages
        if isinstance(item, dict)
    )


def estimate_tokens_for_messages(messages):
    total = 0
    for item in messages:
        content = str(item.get("content") or "")
        total += 4 + math.ceil(len(content) / 4)
    return total


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


def agent_options():
    return {
        "model": DEFAULT_MODEL,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "provider": DEFAULT_PROVIDER,
        "include_reasoning": False,
        "reasoning": REASONING_EXCLUDED,
    }
