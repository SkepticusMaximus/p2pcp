"""p2pcp.chatstore — portable, client-agnostic saved conversations.

One JSON file per chat, so a conversation is a plain, portable record any P2PCP
client can read and write: the FlowCode Mesh tab, the standalone client, a future
phone app. The FILE FORMAT is the contract — JSON on the host FS today (under
``~/.p2pcp/chats``), but the backing store can move to the TernOO native filesystem
or sync over the mesh later without changing a single caller.

A chat file (``<id>.json``)::

    {
      "id": "1a2b3c…",
      "title": "What is balanced ternary?",
      "created": 1754000000,
      "updated": 1754000123,
      "messages": [
        {"role": "user",      "text": "…", "ts": 1754000000},
        {"role": "assistant", "text": "…", "ts": 1754000012, "via": "127.0.0.1:9000"}
      ]
    }

No network, no keys, no ledger — this is local record-keeping, deliberately kept
outside the trustless core.
"""

import itertools
import json
import os
import time

DEFAULT_DIR = os.path.expanduser("~/.p2pcp/chats")
TITLE_MAX = 48
_counter = itertools.count()             # guarantees intra-process id uniqueness


def _slug_title(text):
    """A short human title from the first message (first line, clipped)."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = " ".join(line.split())
    return (line[:TITLE_MAX] + "…") if len(line) > TITLE_MAX else (line or "New chat")


class ChatStore:
    """Saved conversations as one JSON file each, newest-first. All methods are
    forgiving: a missing dir is created on write; a corrupt file is skipped, never
    fatal (a bad record must not wedge the chat list)."""

    def __init__(self, directory=DEFAULT_DIR):
        self.dir = directory

    # ── ids + paths ───────────────────────────────────────────────────────────
    def _path(self, cid):
        return os.path.join(self.dir, f"{cid}.json")

    @staticmethod
    def new_id():
        """A sortable, collision-resistant id: ms clock + pid + an in-process
        counter, so even two ids minted in the same millisecond differ."""
        return (f"{int(time.time() * 1000):x}-{os.getpid() & 0xfff:03x}"
                f"-{next(_counter):x}")

    # ── list / load ───────────────────────────────────────────────────────────
    def list(self):
        """[(id, title, updated), …] newest-first. Skips unreadable files."""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for name in names:
            if not name.endswith(".json"):
                continue
            rec = self._read(name[:-5])
            if rec:
                out.append((rec["id"], rec.get("title") or "New chat",
                            rec.get("updated", 0)))
        out.sort(key=lambda t: t[2], reverse=True)
        return out

    def _read(self, cid):
        try:
            with open(self._path(cid), encoding="utf-8") as fh:
                rec = json.load(fh)
            if isinstance(rec, dict) and rec.get("id"):
                return rec
        except (OSError, ValueError):
            pass
        return None

    def load(self, cid):
        """A chat as {id, title, messages:[{role,text,…}]}, or None."""
        return self._read(cid)

    # ── write ─────────────────────────────────────────────────────────────────
    def save(self, cid, title, messages, created=None):
        """Persist a chat. `messages` is a list of {role, text, …} dicts OR of
        (role, text) pairs (the GUI's transcript form) — both are accepted."""
        now = time.time()                          # sub-second, so rapid saves order
        msgs = []
        for m in messages:
            if isinstance(m, dict):
                msgs.append({k: m[k] for k in m if k in
                             ("role", "text", "ts", "via")})
            else:                                  # (role, text) pair
                role, text = m
                msgs.append({"role": role, "text": text})
        rec = {"id": cid, "title": title or _slug_title(
                   msgs[0]["text"] if msgs else ""),
               "created": created or now, "updated": now, "messages": msgs}
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path(cid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path(cid))           # atomic: no half-written chat
        return rec

    def rename(self, cid, title):
        rec = self._read(cid)
        if not rec:
            return None
        return self.save(cid, title, rec.get("messages", []),
                         created=rec.get("created"))

    def delete(self, cid):
        try:
            os.remove(self._path(cid))
            return True
        except OSError:
            return False

    @staticmethod
    def title_for(first_text):
        """The auto-title a client should use from a chat's first message."""
        return _slug_title(first_text)
