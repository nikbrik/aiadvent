import json
import tempfile
import unittest

try:
    from .agent import ChatAgent, FileMemoryStore
except ImportError:
    from agent import ChatAgent, FileMemoryStore


CLIENT_ID = "11111111-1111-1111-1111-111111111111"


class FakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, messages, **options):
        self.calls.append(messages)
        if messages[0]["content"].startswith("You update long-term memory"):
            return {
                "content": json.dumps({
                    "style": "",
                    "facts": ["user name is Nikita"],
                    "inferences": [],
                    "current_chat_summary": "The user introduced himself as Nikita.",
                })
            }
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


if __name__ == "__main__":
    unittest.main()
