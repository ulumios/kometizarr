"""Persistent cache for external rating API answers (TMDB, OMDb, MDBList).

Change detection evaluates every item on each run; without this cache a daily run would
spend the OMDb/MDBList quota on titles whose ratings Plex does not carry itself."""

import json
import sqlite3
import time
from pathlib import Path

from src.rating_overlay.data_paths import data_file

DEFAULT_TTL = 3 * 24 * 3600
MISS_TTL = 12 * 3600  # a failed or empty answer is retried sooner


class ApiCache:
    def __init__(self, path=None, ttl=DEFAULT_TTL):
        self.path = Path(path) if path else data_file('media_index.sqlite3')
        self.ttl = ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('CREATE TABLE IF NOT EXISTS api_cache (key TEXT PRIMARY KEY, value TEXT, '
                        'fetched_at REAL NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def get_or_fetch(self, key, fetch):
        row = self.db.execute('SELECT value, fetched_at FROM api_cache WHERE key=?', (key,)).fetchone()
        if row:
            value = json.loads(row[0]) if row[0] is not None else None
            if time.time() - row[1] < (self.ttl if value else MISS_TTL):
                return value
        value = fetch()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)',
                            (key, json.dumps(value) if value is not None else None, time.time()))
        return value

    def clear(self):
        with self.db:
            self.db.execute('DELETE FROM api_cache')
