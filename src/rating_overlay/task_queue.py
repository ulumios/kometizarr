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
            attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
            progress TEXT, results TEXT)''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(tasks)')}
        for name in ('progress', 'results'):
            if name not in columns:
                self.db.execute(f'ALTER TABLE tasks ADD COLUMN {name} TEXT')
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
            row = self.db.execute("SELECT id,kind,payload,results FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE tasks SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
                                (time.time(), row[0]))
        return {'id': row[0], 'kind': row[1], 'payload': json.loads(row[2]),
                'results': json.loads(row[3]) if row[3] else {}} if row else None

    def finish(self, task_id, error=None):
        with self.db:
            self.db.execute('UPDATE tasks SET status=?,error=?,updated_at=? WHERE id=?',
                            ('failed' if error else 'completed', error, time.time(), task_id))

    def update_progress(self, task_id, progress, results=None):
        with self.db:
            if results is None:
                self.db.execute('UPDATE tasks SET progress=?,updated_at=? WHERE id=?',
                                (json.dumps(progress), time.time(), task_id))
            else:
                self.db.execute('UPDATE tasks SET progress=?,results=?,updated_at=? WHERE id=?',
                                (json.dumps(progress), json.dumps(results), time.time(), task_id))

    def list(self, limit=30):
        return [dict(id=row[0], kind=row[1], payload=json.loads(row[2]), status=row[3],
                     created_at=row[4], updated_at=row[5], attempts=row[6], error=row[7],
                     progress=json.loads(row[8]) if row[8] else None,
                     results=json.loads(row[9]) if row[9] else None)
                for row in self.db.execute('SELECT id,kind,payload,status,created_at,updated_at,attempts,error,progress,results '
                                           'FROM tasks ORDER BY id DESC LIMIT ?', (min(100, max(1, limit)),))]

    def get(self, task_id):
        row = self.db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
        return row[0] if row else None
