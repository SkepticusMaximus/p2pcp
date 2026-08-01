"""test_chatstore.py — portable saved-conversation store (client-agnostic)."""
import os
import tempfile
import unittest

from p2pcp import chatstore


class TestChatStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="p2pcp-chats-")
        self.store = chatstore.ChatStore(self.dir)

    def test_save_load_roundtrip_pairs_and_dicts(self):
        cid = self.store.new_id()
        # the GUI transcript form: (role, text) pairs
        self.store.save(cid, "Hello chat", [("user", "hi"), ("assistant", "yo")])
        rec = self.store.load(cid)
        self.assertEqual(rec["title"], "Hello chat")
        self.assertEqual([(m["role"], m["text"]) for m in rec["messages"]],
                         [("user", "hi"), ("assistant", "yo")])
        # the dict form (with extra fields) also round-trips
        self.store.save(cid, "Hello chat",
                        [{"role": "assistant", "text": "hey", "via": "127.0.0.1:9000"}])
        self.assertEqual(self.store.load(cid)["messages"][0]["via"], "127.0.0.1:9000")

    def test_list_is_newest_first(self):
        a = self.store.new_id()
        self.store.save(a, "first", [("user", "a")], created=1000)
        # force a later 'updated' by saving b after
        b = "deadbeef-001"
        self.store.save(b, "second", [("user", "b")])
        ids = [i for i, _t, _u in self.store.list()]
        self.assertIn(a, ids)
        self.assertIn(b, ids)
        self.assertEqual(ids[0], b)                # most recently updated first

    def test_auto_title_from_first_message(self):
        self.assertEqual(chatstore.ChatStore.title_for("What is balanced ternary?"),
                         "What is balanced ternary?")
        long = "x" * 100
        self.assertTrue(chatstore.ChatStore.title_for(long).endswith("…"))
        self.assertEqual(chatstore.ChatStore.title_for(""), "New chat")

    def test_rename_and_delete(self):
        cid = self.store.new_id()
        self.store.save(cid, "old", [("user", "q")])
        self.store.rename(cid, "new title")
        self.assertEqual(self.store.load(cid)["title"], "new title")
        self.assertEqual(self.store.load(cid)["messages"][0]["text"], "q")  # kept
        self.assertTrue(self.store.delete(cid))
        self.assertIsNone(self.store.load(cid))

    def test_corrupt_file_is_skipped_not_fatal(self):
        good = self.store.new_id()
        self.store.save(good, "ok", [("user", "q")])
        with open(os.path.join(self.dir, "broken.json"), "w") as fh:
            fh.write("{ this is not json")
        ids = [i for i, _t, _u in self.store.list()]   # must not raise
        self.assertIn(good, ids)

    def test_ids_are_unique(self):
        self.assertNotEqual(self.store.new_id(), self.store.new_id())


if __name__ == "__main__":
    unittest.main()
