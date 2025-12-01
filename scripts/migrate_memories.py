"""Migrate existing preferences/episodic/conversation snippets into long-term memory."""
from __future__ import annotations

import argparse
import re
from typing import List

from leo.clients import EmbeddingClient
from leo.db import Database
from leo.memory import PreferenceStore, EpisodicMemoryStore, LongTermMemoryStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="henry", help="User identifier to migrate")
    parser.add_argument("--conversation-limit", type=int, default=30, help="Number of earliest conversation messages to seed")
    parser.add_argument("--include-tasks", action="store_true", help="If set, will attempt to migrate tasks/reminders (disabled by default).")
    return parser.parse_args()


def has_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text))


def migrate_preferences(user_id: str, ltm: LongTermMemoryStore, prefs: PreferenceStore) -> int:
    entries = prefs.get_all(user_id)
    count = 0
    for key, entry in entries.items():
        content = f"Preference {key}: {entry.value}"
        ltm.add_memory(
            user_id=user_id,
            owner_type="user",
            content=content,
            tags=["preference"],
            importance=0.6,
            plasticity=0.2,
        )
        count += 1
    return count


def migrate_episodic(user_id: str, ltm: LongTermMemoryStore, episodic: EpisodicMemoryStore) -> int:
    episodes = episodic.list_recent(user_id, limit=50)
    count = 0
    for ep in episodes:
        ltm.add_memory(
            user_id=user_id,
            owner_type="user",
            content=f"Episodic summary: {ep.summary}",
            tags=["episodic", "history"],
            importance=0.4,
            plasticity=0.3,
        )
        count += 1
    return count


def migrate_conversations(user_id: str, ltm: LongTermMemoryStore, db: Database, limit: int) -> int:
    rows = db.query(
        """
        SELECT m.role, m.content, m.created_at
        FROM conversation_messages m
        JOIN conversation_sessions s ON m.session_id = s.session_id
        WHERE s.user_id = ?
        ORDER BY m.created_at ASC, m.id ASC
        LIMIT ?
        """,
        (user_id, limit),
    )
    count = 0
    for row in rows:
        content = row["content"]
        if not content or not has_words(content):
            continue
        snippet = content.strip()
        tag = "history"
        if "plan" in content.lower() or "leo" in content.lower():
            tag = "project"
        ltm.add_memory(
            user_id=user_id,
            owner_type="user",
            content=f"Early conversation ({row['role']}): {snippet}",
            tags=[tag],
            importance=0.5,
            plasticity=0.4,
        )
        count += 1
    return count


def main() -> None:
    args = parse_args()
    db = Database()
    db.initialize()

    embedder = EmbeddingClient()
    ltm = LongTermMemoryStore(db=db, embed_client=embedder)
    prefs = PreferenceStore(db=db)
    episodic = EpisodicMemoryStore(db=db)

    total = 0
    total += migrate_preferences(args.user_id, ltm, prefs)
    total += migrate_episodic(args.user_id, ltm, episodic)
    total += migrate_conversations(args.user_id, ltm, db, args.conversation_limit)

    # Optional task/reminder migration intentionally omitted unless explicitly requested
    if args.include_tasks:
        try:
            from leo.memory import TaskStore, ReminderStore

            tasks = TaskStore(db=db).list(args.user_id, limit=50)
            for task in tasks:
                ltm.add_memory(
                    user_id=args.user_id,
                    owner_type="user",
                    content=f"Task: {task.title} (status: {task.status})",
                    tags=["project"],
                    importance=0.4,
                    plasticity=0.4,
                )
                total += 1
            reminders = ReminderStore(db=db).list_pending("9999-12-31", user_id=args.user_id)
            for rem in reminders:
                ltm.add_memory(
                    user_id=args.user_id,
                    owner_type="user",
                    content=f"Reminder: {rem.text} at {rem.remind_at}",
                    tags=["project"],
                    importance=0.3,
                    plasticity=0.4,
                )
                total += 1
        except Exception:
            pass

    print(f"Migrated {total} memories into LTM for user '{args.user_id}'.")


if __name__ == "__main__":
    main()
