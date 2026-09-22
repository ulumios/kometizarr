"""Persistent read index for Plex library browsing and conflict snapshots."""

import json
import logging
import sqlite3
import time
from pathlib import Path

from plexapi.exceptions import NotFound

logger = logging.getLogger(__name__)


class MediaIndex:
    def __init__(self, path='/backups/media_index.sqlite3'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS media (
                library TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
                type TEXT NOT NULL, parent_key TEXT, year INTEGER, item_index INTEGER,
                series TEXT, season INTEGER, thumb TEXT, PRIMARY KEY(library, key));
            CREATE INDEX IF NOT EXISTS media_browse ON media(library, type, parent_key);
            CREATE TABLE IF NOT EXISTS snapshots (
                library TEXT NOT NULL, name TEXT NOT NULL, updated_at REAL NOT NULL,
                payload TEXT, PRIMARY KEY(library, name));
        ''')

    def close(self):
        self.db.close()

    def snapshot(self, library, name):
        row = self.db.execute('SELECT updated_at, payload FROM snapshots WHERE library=? AND name=?',
                              (library, name)).fetchone()
        return (row[0], json.loads(row[1]) if row[1] else None) if row else (0, None)

    def save_snapshot(self, library, name, payload=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)',
                            (library, name, time.time(), json.dumps(payload) if payload is not None else None))

    def replace_library(self, library, items):
        rows = []
        for item in items:
            try:
                rows.append((library, str(item.ratingKey), item.title, item.type,
                             str(getattr(item, 'parentRatingKey', '') or '') or None,
                             getattr(item, 'year', None), getattr(item, 'index', None),
                             getattr(item, 'grandparentTitle', None), getattr(item, 'parentIndex', None),
                             getattr(item, 'thumb', None)))
            except NotFound:
                logger.info('Plex item disappeared while indexing %s: %s', library, item.ratingKey)
        with self.db:
            self.db.execute('DELETE FROM media WHERE library=?', (library,))
            self.db.executemany('INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, NULL)',
                            (library, 'browse', time.time()))

    def browse(self, library, parent_key=None, episodes=False, q='', page=1, page_size=60):
        if parent_key is not None:
            parent = self.db.execute('SELECT type FROM media WHERE library=? AND key=?',
                                     (library, str(parent_key))).fetchone()
            if not parent or parent[0] not in ('show', 'season'):
                raise ValueError('Invalid show or season for this library')
            clause, params = 'parent_key=?', [str(parent_key)]
        else:
            clause, params = ('type=?', ['episode']) if episodes else ('parent_key IS NULL', [])
        where = f'library=? AND {clause}'
        params = [library, *params]
        if q.strip():
            term = '%' + q.strip().lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where += " AND (lower(title) LIKE ? ESCAPE '\\' OR lower(coalesce(series,'')) LIKE ? ESCAPE '\\' OR CAST(year AS TEXT) LIKE ? OR (type='season' AND lower('staffel ' || item_index) LIKE ? ESCAPE '\\'))"
            params.extend([term] * 4)
        total = self.db.execute('SELECT count(*) FROM media WHERE ' + where, params).fetchone()[0]
        page_size = max(1, min(page_size, 100))
        page = max(1, page)
        rows = self.db.execute('SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where +
                               ' ORDER BY coalesce(item_index, 0), title COLLATE NOCASE LIMIT ? OFFSET ?',
                               [*params, page_size, (page - 1) * page_size]).fetchall()
        return {'total': total, 'page': page, 'items': [dict(zip(
            ('key', 'title', 'type', 'year', 'index', 'series', 'season'), row)) for row in rows]}

    def thumb(self, library, rating_key):
        row = self.db.execute('SELECT thumb FROM media WHERE library=? AND key=?',
                              (library, str(rating_key))).fetchone()
        return row[0] if row else None

    def update_thumb(self, library, rating_key, thumb):
        with self.db:
            self.db.execute('UPDATE media SET thumb=? WHERE library=? AND key=?',
                            (thumb, library, str(rating_key)))

    def has_item(self, library, rating_key):
        return self.db.execute('SELECT 1 FROM media WHERE library=? AND key=?',
                               (library, str(rating_key))).fetchone() is not None

    def upsert_item(self, library, item):
        values = (library, str(item.ratingKey), item.title, item.type,
                  str(getattr(item, 'parentRatingKey', '') or '') or None,
                  getattr(item, 'year', None), getattr(item, 'index', None),
                  getattr(item, 'grandparentTitle', None), getattr(item, 'parentIndex', None),
                  getattr(item, 'thumb', None))
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', values)
