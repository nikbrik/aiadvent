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
        PINNED_FACTS_HEADER,
        SUMMARY_MARKER,
        apply_pinned_facts,
        cap_summary,
        maybe_compress_history,
        select_history_messages,
    )
    from .quality_judge import (
        evaluate_fact_recall,
        parse_judge_result,
        safe_judge_answer,
    )
    from . import server as server_module
    from .token_counter import count_message_tokens
except ImportError:
    from agent import (
        COMPARE_RECALL_PROMPT,
        COMPARE_SECRET_PROMPT,
        ChatAgent,
        FileMemoryStore,
    )
    from context_compression import (
        PINNED_FACTS_HEADER,
        SUMMARY_MARKER,
        apply_pinned_facts,
        cap_summary,
        maybe_compress_history,
        select_history_messages,
    )
    from quality_judge import (
        evaluate_fact_recall,
        parse_judge_result,
        safe_judge_answer,
    )
    import server as server_module
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
                "content": "Summary: filler topics covered in demo.",
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
        if COMPARE_SECRET_PROMPT in user_content or user_content == COMPARE_SECRET_PROMPT:
            return {"content": "OK", "prompt_tokens": 20, "completion_tokens": 2}
        if user_content.startswith("Одним коротким предложением:"):
            return {"content": "Короткий ответ про Python.", "prompt_tokens": 30, "completion_tokens": 5}
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
        marker = "Summary: filler topics covered in demo."
        self.assertEqual(memory["history_summary"].count(marker), 1)
        self.assertEqual(memory["history_summary"], cap_summary(marker))

    def test_pinned_facts_prepended_to_summary(self):
        summary = apply_pinned_facts(
            "Older dialog summary.",
            ["codeword: BLUEFOX", "language: Kotlin"],
        )
        self.assertIn(PINNED_FACTS_HEADER, summary)
        self.assertIn("BLUEFOX", summary)
        self.assertIn("Older dialog summary.", summary)

    def test_pinned_facts_do_not_drop_existing_summary_body(self):
        summary = apply_pinned_facts(
            (
                "Pinned facts (never omit):\n"
                "- codeword: BLUEFOX\n"
                "- favorite language: Kotlin\n"
                "- project: Orbit\n\n"
                "Python notes covered decorators, asyncio, dataclass, and pytest."
            ),
            [
                "codeword: BLUEFOX",
                "favorite language: Kotlin",
                "project: Orbit",
            ],
        )
        self.assertIn(PINNED_FACTS_HEADER, summary)
        self.assertIn("BLUEFOX", summary)
        self.assertIn("Python notes covered decorators", summary)

    def test_maybe_compress_history_keeps_pinned_facts(self):
        memory = {
            "current_chat": {
                "messages": [
                    {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
                    for index in range(16)
                ],
            },
            "history_summary": "",
            "compression": {
                "enabled": True,
                "summarized_through": 0,
                "updates": [],
                "pinned_facts": ["codeword: BLUEFOX"],
            },
        }
        llm = RoutingFakeLLM()
        maybe_compress_history(memory, llm, "test-model", {"model": "test-model"})
        self.assertIn(PINNED_FACTS_HEADER, memory["history_summary"])
        self.assertIn("BLUEFOX", memory["history_summary"])


    def test_maybe_compress_history_fallback_updates_summary(self):
        class FailingMergeLLM:
            def __call__(self, messages, **options):
                system = messages[0]["content"] if messages else ""
                if "compress chat history" in system:
                    return {"content": ""}
                return {"content": "ok"}

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
        llm = FailingMergeLLM()
        events = maybe_compress_history(memory, llm, "test-model", {"model": "test-model"})
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["used_fallback"])
        self.assertTrue(memory["history_summary"])
        self.assertEqual(memory["compression"]["summarized_through"], 10)

    def test_compression_disabled_sends_full_history_without_summary_marker(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = RoutingFakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            last_result = None
            for index in range(8):
                last_result = agent.respond(CLIENT_ID, f"msg-{index}", compression=False)

            system_prompt = llm.calls[-1]["messages"][0]["content"]
            self.assertNotIn(SUMMARY_MARKER, system_prompt)
            turn = last_result["last_turn"]
            self.assertEqual(turn["history_tokens_sent"], turn["history_tokens_full"])
            history_roles = [
                item
                for item in llm.calls[-1]["messages"]
                if item.get("role") in ("user", "assistant")
            ]
            self.assertEqual(len(history_roles), 15)


class JudgeSafetyTest(unittest.TestCase):
    def test_evaluate_fact_recall(self):
        result = evaluate_fact_recall(
            "Код BLUEFOX, язык Kotlin, проект Orbit",
            {"codeword": "BLUEFOX", "language": "Kotlin", "project": "Orbit"},
        )
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["facts"]), 3)
        self.assertTrue(all(item["found"] for item in result["facts"]))

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
            self.assertIn("without_compression", comparison)
            self.assertIn("with_compression", comparison)
            self.assertIn("judge", comparison["without_compression"])
            self.assertIn("judge", comparison["with_compression"])
            self.assertIn("tokens_saved", comparison)
            self.assertIn("token_breakdown", comparison)
            self.assertIn("visual", comparison)
            self.assertIn("verdict", comparison)
            self.assertIn("net_saved", comparison["token_breakdown"])
            self.assertIn("headline_before", comparison["visual"])
            self.assertEqual(
                comparison["tokens_saved"],
                comparison["token_breakdown"]["net_saved"],
            )
            with_track = comparison["with_compression"]
            without = comparison["without_compression"]
            self.assertEqual(with_track["replay"], "canned")
            self.assertGreaterEqual(with_track["script_turns"], 56)
            self.assertGreater(with_track["merge_count"], 0)
            self.assertIn("facts", with_track["judge"])
            self.assertIn("recall_payload", with_track)
            self.assertIn("payload_preview", with_track)
            self.assertIn("payload_preview", without)
            self.assertNotIn(SUMMARY_MARKER, without["payload_preview"][0]["content"])
            self.assertIn(SUMMARY_MARKER, with_track["payload_preview"][0]["content"])
            self.assertGreater(with_track["tokens"]["cumulative_net_saved"], 0)
            self.assertEqual(
                without["tokens"]["cumulative_prompt_estimated"],
                with_track["tokens"]["cumulative_prompt_full_estimated"],
            )

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
        self.client = server_module.app.test_client()
        self.client.set_cookie("client_id", CLIENT_ID)
        server_module.app.config["TESTING"] = True

        patcher = patch.object(server_module, "agent", self.agent)
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
        self.assertIn("payload_preview", data)
        self.assertGreater(len(data["payload_preview"]), 0)

    def test_compression_compare_endpoint(self):
        response = self.client.post(
            "/api/demo/compression-compare",
            headers={"Cookie": f"client_id={CLIENT_ID}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        comparison = data["comparison"]
        self.assertIn("without_compression", comparison)
        self.assertIn("with_compression", comparison)
        self.assertIn("tokens_saved", comparison)
        self.assertIn("token_breakdown", comparison)
        self.assertIn("visual", comparison)
        self.assertIn("verdict", comparison)

    def test_visible_demo_steps_update_current_chat(self):
        seeded = self.agent.respond(CLIENT_ID, "Перед демо уже есть история.", compression=True)
        base_count = len(seeded["messages"])

        script_response = self.client.get("/api/demo/compression-script")
        self.assertEqual(script_response.status_code, 200)
        script = script_response.get_json()
        self.assertGreaterEqual(script["total_steps"], 56)
        self.assertEqual(script["steps"][0]["index"], 0)
        user_messages = [step["message"] for step in script["steps"]]
        self.assertGreaterEqual(len(set(user_messages)), 56)

        last = None
        for step in script["steps"]:
            response = self.client.post(
                "/api/demo/compression-step",
                json={"step_index": step["index"]},
            )
            self.assertEqual(response.status_code, 200)
            last = response.get_json()
            self.assertEqual(len(last["messages"]), base_count + ((step["index"] + 1) * 2))
            self.assertEqual(last["demo_step"]["index"], step["index"])
            self.assertIn("payload_preview", last)

        self.assertIsNotNone(last)
        self.assertGreater(last["compression"]["summarized_through"], 0)
        self.assertGreater(len(last["compression"]["updates"]), 0)
        self.assertIn("judge", last)
        self.assertTrue(last["judge"]["passed"])

        repeat_response = self.client.post(
            "/api/demo/compression-step",
            json={"step_index": 0},
        )
        self.assertEqual(repeat_response.status_code, 200)
        repeated = repeat_response.get_json()
        self.assertEqual(len(repeated["messages"]), base_count + (script["total_steps"] * 2) + 2)

    def test_current_comparison_uses_existing_history_without_mutating_chat(self):
        script_response = self.client.get("/api/demo/compression-script")
        self.assertEqual(script_response.status_code, 200)
        script = script_response.get_json()

        for step in script["steps"][:-1]:
            response = self.client.post(
                "/api/demo/compression-step",
                json={"step_index": step["index"]},
            )
            self.assertEqual(response.status_code, 200)

        before = self.client.get("/api/chat").get_json()
        before_count = len(before["messages"])
        self.assertGreater(before["compression"]["summarized_through"], 0)

        response = self.client.post("/api/demo/current-comparison")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        comparison = data["comparison"]
        state = data["state"]
        without = comparison["without_compression"]
        with_track = comparison["with_compression"]

        self.assertEqual(comparison["source"], "current_history")
        self.assertIn("A/B берёт уже накопленную историю", comparison["visual"]["story"][0])
        self.assertIn("A/B recall + merge overhead", [
            row["label"] for row in comparison["visual"]["table"]
        ])
        self.assertIn("Чат не очищался", comparison["verdict"])
        self.assertEqual(len(state["messages"]), before_count)
        self.assertEqual(without["replay"], "current_history")
        self.assertEqual(with_track["replay"], "current_history")
        self.assertIn("payload_preview", without)
        self.assertIn("payload_preview", with_track)
        self.assertNotIn(SUMMARY_MARKER, without["payload_preview"][0]["content"])
        self.assertIn(SUMMARY_MARKER, with_track["payload_preview"][0]["content"])
        self.assertGreater(
            without["tokens"]["final_prompt_estimated"],
            with_track["tokens"]["final_prompt_estimated"],
        )
        self.assertLess(
            with_track["recall_payload"]["messages_sent"],
            without["recall_payload"]["messages_sent"],
        )


if __name__ == "__main__":
    unittest.main()
