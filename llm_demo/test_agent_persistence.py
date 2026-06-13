import json
import tempfile
import unittest

try:
    from .agent import ChatAgent, FileMemoryStore, STRATEGY_IDS, comparison_result_for
    from .demo_script import DEMO_BRANCH_CREATE_STEP, DEMO_BRANCH_SWITCHES, DEMO_MESSAGES
except ImportError:
    from agent import ChatAgent, FileMemoryStore, STRATEGY_IDS, comparison_result_for
    from demo_script import DEMO_BRANCH_CREATE_STEP, DEMO_BRANCH_SWITCHES, DEMO_MESSAGES


CLIENT_ID = "11111111-1111-1111-1111-111111111111"


class FakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, messages, **options):
        self.calls.append(messages)
        prompt_tokens = max(1, sum(len(item.get("content", "")) for item in messages) // 20)
        metadata = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 3,
            "total_tokens": prompt_tokens + 3,
            "cost": 0.000001,
            "duration_ms": 1,
        }
        if messages[0]["content"].startswith("You update long-term memory"):
            return {
                **metadata,
                "content": json.dumps({
                    "style": "",
                    "facts": ["user name is Nikita"],
                    "inferences": [],
                    "current_chat_summary": "The user introduced himself as Nikita.",
                })
            }
        return {**metadata, "content": "Запомнил."}


def prompt_text(messages):
    return "\n".join(item["content"] for item in messages)


class AgentPersistenceTest(unittest.TestCase):
    def test_messages_survive_agent_restart(self):
        with tempfile.TemporaryDirectory() as data_dir:
            first_llm = FakeLLM()
            first_agent = ChatAgent(FileMemoryStore(data_dir), first_llm)
            first_agent.respond(CLIENT_ID, "Меня зовут Никита.")

            saved_path = FileMemoryStore(data_dir).path_for(CLIENT_ID)
            self.assertTrue(saved_path.exists())

            restarted_llm = FakeLLM()
            restarted_agent = ChatAgent(FileMemoryStore(data_dir), restarted_llm)
            snapshot = restarted_agent.snapshot(CLIENT_ID)

            self.assertEqual(
                snapshot["messages"],
                [
                    {"role": "user", "content": "Меня зовут Никита."},
                    {"role": "assistant", "content": "Запомнил."},
                ],
            )

            restarted_agent.respond(CLIENT_ID, "Как меня зовут?")
            restored_prompt = restarted_llm.calls[0]

            self.assertIn(
                {"role": "user", "content": "Меня зовут Никита."},
                restored_prompt,
            )
            self.assertIn(
                {"role": "assistant", "content": "Запомнил."},
                restored_prompt,
            )
            self.assertEqual(
                restored_prompt[-1],
                {"role": "user", "content": "Как меня зовут?"},
            )

    def test_archived_chat_can_be_resumed_and_continued(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            agent = ChatAgent(store, FakeLLM())
            agent.respond(CLIENT_ID, "Чат А: люблю Python.")
            state = agent.start_new_chat(CLIENT_ID)
            old_chat_id = state["archived_chats"][0]["id"]

            agent.respond(CLIENT_ID, "Чат Б: люблю Flask.")

            restarted_llm = FakeLLM()
            restarted_agent = ChatAgent(FileMemoryStore(data_dir), restarted_llm)
            resumed = restarted_agent.resume_chat(CLIENT_ID, old_chat_id)

            self.assertEqual(
                resumed["messages"],
                [
                    {"role": "user", "content": "Чат А: люблю Python."},
                    {"role": "assistant", "content": "Запомнил."},
                ],
            )
            self.assertTrue(
                any(
                    item["message_count"] == 2 and "messages" not in item
                    for item in resumed["archived_chats"]
                )
            )
            saved_memory = store.load(CLIENT_ID)
            self.assertTrue(
                any(
                    item["messages"][0]["content"] == "Чат Б: люблю Flask."
                    for item in saved_memory["archived_chats"]
                )
            )

            restarted_agent.respond(CLIENT_ID, "Продолжим чат А.")
            resumed_prompt = restarted_llm.calls[0]

            self.assertIn(
                {"role": "user", "content": "Чат А: люблю Python."},
                resumed_prompt,
            )
            self.assertNotIn(
                {"role": "user", "content": "Чат Б: люблю Flask."},
                resumed_prompt,
            )

    def test_invalid_memory_version_falls_back_to_legacy_migration(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            path = store.path_for(CLIENT_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "version": "not-a-number",
                    "current_chat": {
                        "messages": [
                            {"role": "user", "content": "Меня зовут Никита."},
                        ],
                    },
                }),
                encoding="utf-8",
            )

            snapshot = ChatAgent(store, FakeLLM()).snapshot(CLIENT_ID)

            self.assertEqual(snapshot["active_strategy"], "profile_summaries")
            self.assertEqual(snapshot["messages"], [{"role": "user", "content": "Меня зовут Никита."}])


class ContextStrategyTest(unittest.TestCase):
    def test_strategies_do_not_share_prompt_blocks(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)

            agent.set_strategy(CLIENT_ID, "sliding_window")
            agent.respond(CLIENT_ID, "SLIDING_ONLY ранний контекст.")

            agent.set_strategy(CLIENT_ID, "sticky_facts")
            agent.respond(CLIENT_ID, "Цель продукта: семейный задачник.")
            sticky_prompt = prompt_text(llm.calls[-1])

            self.assertIn("Sticky facts JSON", sticky_prompt)
            self.assertIn("семейный задачник", sticky_prompt)
            self.assertNotIn("SLIDING_ONLY", sticky_prompt)

    def test_sliding_window_drops_early_messages(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "sliding_window")

            for index in range(4):
                agent.respond(CLIENT_ID, f"Сообщение {index} EARLY_DETAIL")
            agent.respond(CLIENT_ID, "Финальный вопрос?")

            final_prompt = prompt_text(llm.calls[-1])
            self.assertNotIn("Сообщение 0 EARLY_DETAIL", final_prompt)
            self.assertIn("Сообщение 3 EARLY_DETAIL", final_prompt)
            self.assertLessEqual(len(agent.snapshot(CLIENT_ID)["messages"]), 4)

    def test_sliding_window_normalizes_loaded_state_to_window(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            path = store.path_for(CLIENT_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            messages = [
                {"role": "user", "content": f"stored message {index}"}
                for index in range(8)
            ]
            path.write_text(
                json.dumps({
                    "version": 2,
                    "active_strategy": "sliding_window",
                    "strategies": {
                        "sliding_window": {
                            "messages": messages,
                        }
                    },
                }),
                encoding="utf-8",
            )

            snapshot = ChatAgent(store, FakeLLM()).snapshot(CLIENT_ID)

            self.assertEqual(len(snapshot["messages"]), 4)
            self.assertNotIn("stored message 0", prompt_text(snapshot["messages"]))
            self.assertIn("stored message 7", prompt_text(snapshot["messages"]))

    def test_sticky_facts_are_sent_with_recent_messages(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "sticky_facts")

            agent.respond(
                CLIENT_ID,
                "Критично: MVP нужен за 3 недели, приложение offline-first, без ML.",
            )
            agent.respond(CLIENT_ID, "Что ты помнишь?")
            final_prompt = prompt_text(llm.calls[-1])

            self.assertIn('"deadline": "MVP за 3 недели"', final_prompt)
            self.assertIn('"offline_first": "работает offline-first"', final_prompt)
            self.assertIn('"budget": "бюджет без ML и машинного обучения"', final_prompt)

    def test_branching_isolates_branch_transcripts(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "branching")

            agent.respond(CLIENT_ID, "Общая база.")
            agent.create_checkpoint(CLIENT_ID)
            agent.create_branches(CLIENT_ID)
            agent.switch_branch(CLIENT_ID, "branch_a")
            agent.respond(CLIENT_ID, "A_ONLY быстрый MVP.")
            agent.switch_branch(CLIENT_ID, "branch_b")
            agent.respond(CLIENT_ID, "B_ONLY enterprise.")
            agent.switch_branch(CLIENT_ID, "branch_a")
            agent.respond(CLIENT_ID, "Проверь ветку A.")

            final_prompt = prompt_text(llm.calls[-1])
            self.assertIn("A_ONLY", final_prompt)
            self.assertNotIn("B_ONLY", final_prompt)

    def test_branching_recovers_empty_branch_state(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            path = store.path_for(CLIENT_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "version": 2,
                    "active_strategy": "branching",
                    "strategies": {
                        "branching": {
                            "active_branch": "missing",
                            "branches": {},
                        }
                    },
                }),
                encoding="utf-8",
            )

            snapshot = ChatAgent(store, FakeLLM()).snapshot(CLIENT_ID)

            self.assertEqual(snapshot["strategy_state"]["active_branch"], "main")
            self.assertEqual(len(snapshot["strategy_state"]["branches"]), 1)

    def test_token_cut_uses_budget_instead_of_message_count(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "token_cut")

            agent.respond(CLIENT_ID, "EARLY_DETAIL " + ("очень длинный текст " * 120))
            agent.respond(CLIENT_ID, "Короткий свежий контекст.")
            agent.respond(CLIENT_ID, "Финальный вопрос?")

            final_prompt = prompt_text(llm.calls[-1])
            self.assertNotIn("EARLY_DETAIL", final_prompt)
            self.assertIn("Короткий свежий контекст.", final_prompt)

    def test_context_leveling_builds_structured_levels(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "context_leveling")

            agent.respond(CLIENT_ID, "Цель продукта: семейный задачник для родителей и детей 7-12.")
            agent.respond(CLIENT_ID, "Финальный вопрос?")
            final_prompt = prompt_text(llm.calls[-1])

            self.assertIn("Context levels", final_prompt)
            self.assertIn("семейный задачник", final_prompt)
            self.assertIn("родители и дети", final_prompt)

    def test_conversation_recreation_uses_state_without_raw_history(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "conversation_recreation")

            agent.respond(CLIENT_ID, "Цель продукта: семейный задачник.")
            agent.respond(CLIENT_ID, "Промежуточный шум, который не должен быть raw history.")
            agent.respond(CLIENT_ID, "Финальный вопрос?")
            final_prompt = prompt_text(llm.calls[-1])

            self.assertIn("Recreated conversation state", final_prompt)
            self.assertIn("семейный задачник", final_prompt)
            self.assertNotIn("Промежуточный шум, который не должен быть raw history.", final_prompt)
            self.assertNotIn("Запомнил.", final_prompt)

    def test_profile_memory_history_summaries_remains_available(self):
        with tempfile.TemporaryDirectory() as data_dir:
            llm = FakeLLM()
            agent = ChatAgent(FileMemoryStore(data_dir), llm)
            agent.set_strategy(CLIENT_ID, "profile_summaries")

            agent.respond(CLIENT_ID, "Меня зовут Никита.")
            agent.respond(CLIENT_ID, "Как меня зовут?")
            final_prompt = prompt_text(llm.calls[-2])

            self.assertIn("Profile Memory + History Summaries", final_prompt)
            self.assertIn("The user introduced himself as Nikita.", final_prompt)

    def test_profile_memory_metrics_include_auxiliary_update_calls(self):
        with tempfile.TemporaryDirectory() as data_dir:
            agent = ChatAgent(FileMemoryStore(data_dir), FakeLLM())
            agent.set_strategy(CLIENT_ID, "profile_summaries")

            snapshot = agent.respond(CLIENT_ID, "Меня зовут Никита.")
            metrics = snapshot["strategy_state"]["metrics"]

            self.assertEqual(metrics["main_calls"], 1)
            self.assertEqual(metrics["auxiliary_calls"], 1)
            self.assertEqual(metrics["calls"], 2)
            self.assertGreater(metrics["total_tokens"], snapshot["context_report"]["actual_total_tokens"])

    def test_same_demo_scenario_runs_for_all_strategies(self):
        with tempfile.TemporaryDirectory() as data_dir:
            agent = ChatAgent(FileMemoryStore(data_dir), FakeLLM())
            results = []

            for strategy_id in STRATEGY_IDS:
                agent.set_strategy(CLIENT_ID, strategy_id)
                agent.reset_strategy(CLIENT_ID, strategy_id)

                for progress, message in enumerate(DEMO_MESSAGES):
                    step_number = progress + 1
                    if strategy_id == "branching" and step_number in DEMO_BRANCH_SWITCHES:
                        agent.switch_branch(CLIENT_ID, DEMO_BRANCH_SWITCHES[step_number])

                    agent.respond(CLIENT_ID, message)

                    if strategy_id == "branching" and step_number == DEMO_BRANCH_CREATE_STEP:
                        agent.create_checkpoint(CLIENT_ID)
                        agent.create_branches(CLIENT_ID)

                results.append(comparison_result_for(agent.snapshot(CLIENT_ID)))

            self.assertEqual(len(results), 7)
            self.assertEqual({item["strategy_id"] for item in results}, set(STRATEGY_IDS))


if __name__ == "__main__":
    unittest.main()
