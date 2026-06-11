import json
import tempfile
import unittest

try:
    from .agent import ChatAgent, FileMemoryStore
    from .context_compression import SUMMARY_MARKER
except ImportError:
    from agent import ChatAgent, FileMemoryStore
    from context_compression import SUMMARY_MARKER


CLIENT_ID = "11111111-1111-1111-1111-111111111111"


class FakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, messages, **options):
        self.calls.append(messages)
        system = messages[0]["content"] if messages else ""
        if "compress chat history" in system:
            return {"content": "Compressed summary of prior chat."}
        return {"content": "Запомнил."}


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

    def test_compression_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            agent = ChatAgent(store, FakeLLM())
            for index in range(12):
                agent.respond(CLIENT_ID, f"msg {index}", compression=True)

            saved = store.load(CLIENT_ID)
            self.assertGreater(saved["compression"]["summarized_through"], 0)

            restarted = ChatAgent(store, FakeLLM())
            snapshot = restarted.snapshot(CLIENT_ID)
            self.assertEqual(snapshot["compression"]["summarized_through"], saved["compression"]["summarized_through"])
            self.assertEqual(snapshot["history_summary"], saved["history_summary"])

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

    def test_resume_does_not_inject_archive_summary_into_prompt(self):
        with tempfile.TemporaryDirectory() as data_dir:
            store = FileMemoryStore(data_dir)
            agent = ChatAgent(store, FakeLLM())
            agent.respond(CLIENT_ID, "Чат А: люблю Python.")
            state = agent.start_new_chat(CLIENT_ID)
            old_chat_id = state["archived_chats"][0]["id"]
            agent.respond(CLIENT_ID, "Чат Б: люблю Flask.")

            restarted_agent = ChatAgent(store, FakeLLM())
            restarted_agent.resume_chat(CLIENT_ID, old_chat_id)
            snapshot = restarted_agent.snapshot(CLIENT_ID)
            self.assertEqual(snapshot["history_summary"], "")

            llm = FakeLLM()
            restarted_agent = ChatAgent(store, llm)
            restarted_agent.respond(CLIENT_ID, "Продолжим чат А.", compression=True)
            system_prompt = llm.calls[0][0]["content"]
            self.assertNotIn(SUMMARY_MARKER, system_prompt)


if __name__ == "__main__":
    unittest.main()
