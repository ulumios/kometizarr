"""Durable single-worker queue for overlay and IMDb operations."""

import json
import sqlite3
import time
from pathlib import Path


class TaskQueue:
    def __init__(self, path='/backups/tasks.sqlite3'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, error TEXT)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_next ON tasks(status, id)')
        self.db.commit()

    def close(self):
        self.db.close()

    def add(self, kind, payload):
        with self.db:
            cursor = self.db.execute('INSERT INTO tasks (kind,payload,status,created_at,updated_at) VALUES (?, ?, ?, ?, ?)',
                                     (kind, json.dumps(payload), 'queued', time.time(), time.time()))
        return cursor.lastrowid

    def resume(self):
        with self.db:
            self.db.execute("UPDATE tasks SET status='queued', updated_at=? WHERE status='running'", (time.time(),))

    def claim(self):
        with self.db:
            row = self.db.execute("SELECT id,kind,payload FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE tasks SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
                                (time.time(), row[0]))
        return {'id': row[0], 'kind': row[1], 'payload': json.loads(row[2])} if row else None

    def finish(self, task_id, error=None):
        with self.db:
            self.db.execute('UPDATE tasks SET status=?,error=?,updated_at=? WHERE id=?',
                            ('failed' if error else 'completed', error, time.time(), task_id))

    def list(self, limit=30):
        return [dict(zip(('id', 'kind', 'payload', 'status', 'created_at', 'updated_at', 'attempts', 'error'),
                         (row[0], row[1], json.loads(row[2]), *row[3:])))
                for row in self.db.execute('SELECT id,kind,payload,status,created_at,updated_at,attempts,error '
                                           'FROM tasks ORDER BY id DESC LIMIT ?', (min(100, max(1, limit)),))]
