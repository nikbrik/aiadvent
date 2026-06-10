import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from .agent import ChatAgent, FileMemoryStore
    from .token_counter import count_message_tokens, count_text_tokens
except ImportError:
    from agent import ChatAgent, FileMemoryStore
    from token_counter import count_message_tokens, count_text_tokens


CLIENT_ID = "22222222-2222-2222-2222-222222222222"


class FakeLLM:
    def __init__(self, reply="Короткий ответ.", usage=None):
        self.calls = []
        self.reply = reply
        self.usage = usage or {
            "prompt_tokens": 42,
            "completion_tokens": 7,
            "total_tokens": 49,
            "cost": 0.000012,
        }

    def __call__(self, messages, **options):
        self.calls.append({"messages": messages, "options": options})
        return {
            "content": self.reply,
            **self.usage,
        }


class TokenCounterTest(unittest.TestCase):
    def test_count_text_tokens_is_deterministic(self):
        first = count_text_tokens("hello token accounting")
        second = count_text_tokens("hello token accounting")
        self.assertEqual(first, second)
        self.assertGreater(first, 0)

    def test_count_message_tokens_includes_overhead(self):
        messages = [{"role": "user", "content": "hi"}]
        text_only = count_text_tokens("hi")
        self.assertGreater(count_message_tokens(messages), text_only)


class TokenAccountingTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "TOKEN_CONTEXT_LIMIT": "4096",
                "TOKEN_MAX_TOKENS": "512",
                "PROMPT_PRICE_PER_1M_TOKENS": "1.0",
                "COMPLETION_PRICE_PER_1M_TOKENS": "2.0",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_history_tokens_grow_after_additional_turns(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            first = agent.respond(CLIENT_ID, "Первое сообщение.")
            second = agent.respond(CLIENT_ID, "Второе сообщение.")

            self.assertEqual(first["last_turn"]["history_tokens"], 0)
            self.assertGreater(second["last_turn"]["history_tokens"], 0)
            self.assertEqual(len(llm.calls), 2)

    def test_actual_usage_is_copied_into_turn_stats(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM(usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": 0.0005,
            })
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            result = agent.respond(CLIENT_ID, "Проверка usage.")

            turn = result["last_turn"]
            self.assertEqual(turn["prompt_tokens_actual"], 100)
            self.assertEqual(turn["response_tokens_actual"], 20)
            self.assertEqual(turn["total_tokens_actual"], 120)
            self.assertEqual(turn["turn_cost_actual"], 0.0005)

    def test_estimated_response_tokens_used_when_actual_missing(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM(
                reply="Это estimated response.",
                usage={
                    "prompt_tokens": 30,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "cost": None,
                },
            )
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            result = agent.respond(CLIENT_ID, "Без completion usage.")

            turn = result["last_turn"]
            self.assertIsNone(turn["response_tokens_actual"])
            self.assertGreater(turn["response_tokens_estimated"], 0)

    def test_cost_estimate_calculated_when_prices_configured(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM(
                usage={
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 1_000_000,
                    "total_tokens": 2_000_000,
                    "cost": None,
                },
            )
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            result = agent.respond(CLIENT_ID, "Оценка стоимости.")

            self.assertAlmostEqual(result["last_turn"]["turn_cost_estimated"], 3.0)
            self.assertAlmostEqual(result["cumulative"]["cost_estimated"], 3.0)

    def test_cumulative_total_tokens_estimated_tracks_turns(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            first = agent.respond(CLIENT_ID, "Первое.")
            second = agent.respond(CLIENT_ID, "Второе.")

            self.assertGreater(first["last_turn"]["total_tokens_estimated"], 0)
            self.assertGreater(
                second["cumulative"]["total_tokens_estimated"],
                first["cumulative"]["total_tokens_estimated"],
            )

    def test_zero_cost_actual_is_preserved(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM(usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.0,
            })
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            result = agent.respond(CLIENT_ID, "Бесплатный ответ.")

            self.assertEqual(result["last_turn"]["turn_cost_actual"], 0.0)
            self.assertEqual(result["cumulative"]["cost_actual"], 0.0)

    def test_overflow_is_blocked_before_llm_call(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)

            with patch.dict(os.environ, {"TOKEN_CONTEXT_LIMIT": "128", "TOKEN_MAX_TOKENS": "64"}, clear=False):
                result = agent.run_demo_overflow(CLIENT_ID)

            self.assertEqual(len(llm.calls), 0)
            self.assertEqual(result["last_turn"]["status"], "overflow")
            self.assertFalse(result["last_turn"]["model_called"])
            self.assertIn("over_by", result["overflow"])

    def test_snapshot_exposes_token_data_for_ui(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.respond(CLIENT_ID, "UI snapshot.")

            snapshot = agent.snapshot(CLIENT_ID)
            self.assertIn("turns", snapshot)
            self.assertIn("cumulative", snapshot)
            self.assertIn("prompt_usage", snapshot)
            self.assertIn("context_limit", snapshot)
            self.assertIn("pricing", snapshot)
            self.assertIsNotNone(snapshot["current_turn"])


class ApiTokenAccountingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(
            os.environ,
            {
                "TOKEN_CONTEXT_LIMIT": "4096",
                "TOKEN_MAX_TOKENS": "512",
            },
            clear=False,
        )
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.llm = FakeLLM()
        self.agent = ChatAgent(FileMemoryStore(self.data_dir), self.llm)
        self.agent_patch = patch("server.agent", self.agent)
        self.agent_patch.start()

        import server

        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.client.set_cookie("client_id", CLIENT_ID)

    def tearDown(self):
        self.agent_patch.stop()

    def test_get_chat_returns_token_payload(self):
        self.agent.respond(CLIENT_ID, "Проверка API.")

        response = self.client.get("/api/chat")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("turns", data)
        self.assertIn("cumulative", data)
        self.assertIn("total_tokens_estimated", data["cumulative"])
        self.assertIn("prompt_usage", data)
        self.assertIn("pricing", data)

    def test_post_chat_overflow_returns_413(self):
        with patch.dict(os.environ, {"TOKEN_CONTEXT_LIMIT": "128", "TOKEN_MAX_TOKENS": "64"}, clear=False):
            response = self.client.post("/api/demo/overflow")

        self.assertEqual(response.status_code, 413)
        data = response.get_json()
        self.assertEqual(data["last_turn"]["status"], "overflow")
        self.assertIn("overflow", data)
        self.assertEqual(len(self.llm.calls), 0)

    def test_delete_chat_clears_token_stats(self):
        self.agent.respond(CLIENT_ID, "Сообщение.")

        response = self.client.delete("/api/chat")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["messages"], [])
        self.assertEqual(data["turns"], [])
        self.assertEqual(data["cumulative"]["total_tokens_estimated"], 0)


if __name__ == "__main__":
    unittest.main()
