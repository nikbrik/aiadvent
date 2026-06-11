import json
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from .agent import (
        COMPARE_RECALL_PROMPT,
        COMPARE_SECRET_PROMPT,
        ChatAgent,
        FileMemoryStore,
    )
    from .context_compression import (
        cap_summary,
        maybe_compress_history,
        select_history_messages,
    )
    from .quality_judge import parse_judge_result, safe_judge_answer
    from .server import app
    from .token_counter import count_message_tokens
except ImportError:
    from agent import (
        COMPARE_RECALL_PROMPT,
        COMPARE_SECRET_PROMPT,
        ChatAgent,
        FileMemoryStore,
    )
    from context_compression import (
        cap_summary,
        maybe_compress_history,
        select_history_messages,
    )
    from quality_judge import parse_judge_result, safe_judge_answer
    from server import app
    from token_counter import count_message_tokens


CLIENT_ID = "33333333-3333-3333-3333-333333333333"


class RoutingFakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, messages, **options):
        self.calls.append({"messages": messages, "options": options})
        system = messages[0]["content"] if messages else ""

        if "compress chat history" in system or "merge conversation history" in system:
            return {
                "content": "Summary: BLUEFOX, Kotlin, Orbit mentioned earlier.",
                "prompt_tokens": 50,
                "completion_tokens": 12,
            }

        if "evaluate answer quality" in system:
            return {
                "content": json.dumps({
                    "passed": True,
                    "score": 0.9,
                    "note": "Most facts recalled.",
                })
            }

        user_content = messages[-1]["content"]
        if user_content == COMPARE_RECALL_PROMPT:
            return {"content": "BLUEFOX, Kotlin, Orbit", "prompt_tokens": 80, "completion_tokens": 6}
        if user_content == COMPARE_SECRET_PROMPT:
            return {"content": "OK", "prompt_tokens": 20, "completion_tokens": 2}
        return {"content": "Короткий ответ про Python.", "prompt_tokens": 30, "completion_tokens": 5}


class ContextCompressionLogicTest(unittest.TestCase):
    def test_select_prompt_messages_keeps_tail_when_compressed(self):
        memory = {
            "current_chat": {
                "messages": [
                    {"role": "user", "content": f"msg-{index}"}
                    for index in range(16)
                ],
            },
            "history_summary": "older summary",
            "compression": {
                "enabled": True,
                "summarized_through": 10,
                "updates": [],
            },
        }
        tail, meta = select_history_messages(memory, True)
        self.assertEqual(len(tail), 6)
        self.assertEqual(meta["messages_sent"], 6)
        self.assertEqual(meta["messages_total"], 16)

    def test_maybe_compress_history_triggers_once_at_ten_messages(self):
        memory = {
            "current_chat": {
                "messages": [
                    {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
                    for index in range(16)
                ],
            },
            "history_summary": "",
            "compression": {"enabled": True, "summarized_through": 0, "updates": []},
        }
        llm = RoutingFakeLLM()
        events = maybe_compress_history(memory, llm, "test-model", {"model": "test-model"})
        self.assertEqual(len(events), 1)
        self.assertEqual(memory["compression"]["summarized_through"], 10)
        self.assertTrue(memory["history_summary"])

    def test_llm_merge_replaces_summary_without_concat_duplication(self):
        memory = {
            "current_chat": {
                "messages": [
                    {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
                    for index in range(26)
                ],
            },
            "history_summary": "",
            "compression": {"enabled": True, "summarized_through": 0, "updates": []},
        }
        llm = RoutingFakeLLM()
        events = maybe_compress_history(memory, llm, "test-model", {"model": "test-model"})
        self.assertGreaterEqual(len(events), 2)
        marker = "Summary: BLUEFOX, Kotlin, Orbit mentioned earlier."
        self.assertEqual(memory["history_summary"].count(marker), 1)
        self.assertEqual(memory["history_summary"], cap_summary(marker))


class JudgeSafetyTest(unittest.TestCase):
    def test_safe_judge_answer_handles_invalid_json(self):
        class BadJudgeLLM:
            def __call__(self, messages, **options):
                return {"content": "not-json"}

        result = safe_judge_answer(
            BadJudgeLLM(),
            "question",
            "answer",
            {"codeword": "X"},
            {},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("judge failed", result["note"])


class ContextCompressionAgentTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CONTEXT_KEEP_RECENT_MESSAGES": "6",
                "CONTEXT_COMPRESS_EVERY": "10",
                "CONTEXT_COMPRESSION_ENABLED": "true",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_compression_reduces_prompt_tokens_on_long_dialog(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = RoutingFakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)

            without_last = None
            for index in range(10):
                result = agent.respond(CLIENT_ID, f"Сообщение {index}", compression=False)
                without_last = result["last_turn"]

            agent.clear(CLIENT_ID)
            with_last = None
            for index in range(10):
                result = agent.respond(CLIENT_ID, f"Сообщение {index}", compression=True)
                with_last = result["last_turn"]

            self.assertGreater(
                without_last["prompt_tokens_full_estimated"],
                with_last["prompt_tokens_estimated"],
            )

    def test_compare_demo_returns_both_tracks(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = RoutingFakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            result = agent.run_demo_compression_compare(CLIENT_ID)

            comparison = result["comparison"]
            self.assertIn("without", comparison)
            self.assertIn("with", comparison)
            self.assertIn("judge", comparison["without"])
            self.assertIn("judge", comparison["with"])
            self.assertIn("tokens_saved", comparison)

    def test_history_summary_persists_after_reload(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            llm = RoutingFakeLLM()
            agent = ChatAgent(store, llm)

            for index in range(12):
                agent.respond(CLIENT_ID, f"Persist {index}", compression=True)

            saved = store.load(CLIENT_ID)
            self.assertGreater(saved["compression"]["summarized_through"], 0)
            self.assertTrue(saved["history_summary"])

            restarted = ChatAgent(store, RoutingFakeLLM())
            snapshot = restarted.snapshot(CLIENT_ID)
            self.assertEqual(snapshot["compression"]["summarized_through"], saved["compression"]["summarized_through"])
            self.assertEqual(snapshot["history_summary"], saved["history_summary"])

    def test_judge_persisted_in_turns_after_compare_recall(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            agent = ChatAgent(store, RoutingFakeLLM())
            memory = store.load(CLIENT_ID)
            agent._complete_turn(
                CLIENT_ID,
                memory,
                COMPARE_RECALL_PROMPT,
                run_judge=True,
            )
            saved = store.load(CLIENT_ID)
            self.assertIn("judge", saved["turns"][-1])
            self.assertTrue(saved["turns"][-1]["judge"]["passed"])


class JudgeParserTest(unittest.TestCase):
    def test_parse_judge_result(self):
        parsed = parse_judge_result('{"passed": true, "score": 0.85, "note": "ok"}')
        self.assertTrue(parsed["passed"])
        self.assertAlmostEqual(parsed["score"], 0.85)


class CompressionApiTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CONTEXT_KEEP_RECENT_MESSAGES": "6",
                "CONTEXT_COMPRESS_EVERY": "10",
            },
            clear=False,
        )
        self.env.start()
        self.data_dir = tempfile.TemporaryDirectory()
        self.store = FileMemoryStore(self.data_dir.name)
        self.llm = RoutingFakeLLM()
        self.agent = ChatAgent(self.store, self.llm)
        self.client = app.test_client()
        app.config["TESTING"] = True

        patcher = patch("server.agent", self.agent)
        self.addCleanup(patcher.stop)
        patcher.start()

    def tearDown(self):
        self.env.stop()
        self.data_dir.cleanup()

    def test_get_chat_includes_summary_fields(self):
        self.agent.respond(CLIENT_ID, "Привет", compression=True)
        response = self.client.get(
            "/api/chat",
            headers={"Cookie": f"client_id={CLIENT_ID}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("history_summary", data)
        self.assertIn("compression", data)
        self.assertIn("turns", data)

    def test_compression_compare_endpoint(self):
        response = self.client.post(
            "/api/demo/compression-compare",
            headers={"Cookie": f"client_id={CLIENT_ID}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("comparison", data)


if __name__ == "__main__":
    unittest.main()
