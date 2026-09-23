"""Persistent read index for Plex library browsing and conflict snapshots."""

import json
import logging
import sqlite3
import time
import hashlib
import os
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
            CREATE TABLE IF NOT EXISTS conflicts (
                library TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
                type TEXT NOT NULL, show_key TEXT, season_key TEXT,
                payload TEXT NOT NULL, PRIMARY KEY(library, key));
            CREATE INDEX IF NOT EXISTS conflicts_parent ON conflicts(library, show_key, season_key);
            CREATE TABLE IF NOT EXISTS artwork (
                library TEXT NOT NULL, key TEXT NOT NULL, mime TEXT NOT NULL,
                thumb TEXT, updated_at REAL NOT NULL, PRIMARY KEY(library, key));
            CREATE TABLE IF NOT EXISTS origins (
                library TEXT NOT NULL, key TEXT NOT NULL, source TEXT NOT NULL,
                poster_id TEXT, updated_at REAL NOT NULL, PRIMARY KEY(library, key));
        ''')
        # One-time migration of previously recorded JSON conflicts.
        with self.db:
            for library, payload in self.db.execute(
                    "SELECT library,payload FROM snapshots WHERE name='conflicts' AND payload IS NOT NULL"):
                for entry in json.loads(payload):
                    key = str(entry.get('key', ''))
                    if not key:
                        continue
                    parent = self.db.execute('SELECT parent_key FROM media WHERE library=? AND key=?',
                                             (library, key)).fetchone()
                    season_key = parent[0] if parent and entry.get('type') == 'episode' else None
                    show_key = None
                    if season_key:
                        row = self.db.execute('SELECT parent_key FROM media WHERE library=? AND key=?',
                                              (library, season_key)).fetchone()
                        show_key = row[0] if row else None
                    self.db.execute('INSERT OR IGNORE INTO conflicts VALUES (?, ?, ?, ?, ?, ?, ?)',
                                    (library, key, entry.get('title', ''), entry.get('type', ''),
                                     show_key, season_key, json.dumps(entry)))
            self.db.execute("DELETE FROM snapshots WHERE name='conflicts'")

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

    def replace_library(self, library, items, progress=None):
        rows = []
        for position, item in enumerate(items, 1):
            try:
                rows.append((library, str(item.ratingKey), item.title, item.type,
                             str(getattr(item, 'parentRatingKey', '') or '') or None,
                             getattr(item, 'year', None), getattr(item, 'index', None),
                             getattr(item, 'grandparentTitle', None), getattr(item, 'parentIndex', None),
                             getattr(item, 'thumb', None)))
            except NotFound:
                logger.info('Plex item disappeared while indexing %s: %s', library, item.ratingKey)
            if progress is not None and (position % 50 == 0 or position == len(items)):
                progress.update(scanned=position, total=len(items), phase='Speichere Bibliothek')
        with self.db:
            self.db.execute('DELETE FROM media WHERE library=?', (library,))
            self.db.executemany('INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
            self.db.execute('DELETE FROM conflicts WHERE library=? AND key NOT IN '
                            '(SELECT key FROM media WHERE library=?)', (library, library))
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, NULL)',
                            (library, 'browse', time.time()))

    def browse(self, library, parent_key=None, episodes=False, q='', page=1, page_size=60,
               conflicts_only=False):
        parent_row = None
        if parent_key is not None:
            parent_row = self.db.execute(
                'SELECT type, title, item_index, series FROM media WHERE library=? AND key=?',
                (library, str(parent_key))).fetchone()
            if not parent_row or parent_row[0] not in ('show', 'season'):
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
        page_size = max(1, min(page_size, 100))
        page = max(1, page)
        select = 'SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where
        order = ' ORDER BY coalesce(item_index, 0), title COLLATE NOCASE'
        if conflicts_only:
            if parent_row and parent_row[0] == 'show':
                where += ' AND (key IN (SELECT key FROM conflicts WHERE library=?) OR key IN (SELECT season_key FROM conflicts WHERE library=? AND show_key=?))'
                params.extend([library, library, str(parent_key)])
            elif parent_row and parent_row[0] == 'season':
                where += ' AND key IN (SELECT key FROM conflicts WHERE library=?)'
                params.append(library)
            else:
                where += ' AND (key IN (SELECT key FROM conflicts WHERE library=?) OR key IN (SELECT show_key FROM conflicts WHERE library=?))'
                params.extend([library, library])
            select = 'SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where
        total = self.db.execute('SELECT count(*) FROM media WHERE ' + where, params).fetchone()[0]
        rows = self.db.execute(select + order + ' LIMIT ? OFFSET ?',
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

    def record_conflict(self, library, item, payload):
        show_key = str(getattr(item, 'grandparentRatingKey', None) or '') or None
        season_key = str(getattr(item, 'parentRatingKey', None) or '') or None
        if item.type == 'show':
            show_key = str(item.ratingKey)
        elif item.type == 'season':
            show_key = season_key
            season_key = str(item.ratingKey)
        elif item.type == 'episode' and not show_key and season_key:
            row = self.db.execute('SELECT parent_key FROM media WHERE library=? AND key=?',
                                  (library, season_key)).fetchone()
            show_key = row[0] if row else None
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO conflicts VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (library, str(item.ratingKey), item.title, item.type,
                             show_key, season_key, json.dumps(payload)))

    def forget_conflict(self, library, key):
        with self.db:
            self.db.execute('DELETE FROM conflicts WHERE library=? AND key=?', (library, str(key)))

    def has_conflict(self, library, key):
        return self.db.execute('SELECT 1 FROM conflicts WHERE library=? AND key=?',
                               (library, str(key))).fetchone() is not None

    def conflicts(self, library):
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT payload FROM conflicts WHERE library=? ORDER BY title', (library,))]

    def origin(self, library, key):
        return self.db.execute('SELECT source, poster_id FROM origins WHERE library=? AND key=?',
                               (library, str(key))).fetchone()

    def record_origin(self, library, item, source):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO origins VALUES (?, ?, ?, ?, ?)',
                            (library, str(item.ratingKey), source,
                             str(getattr(item, 'thumb', '') or ''), time.time()))

    def artwork_path(self, library, key):
        digest = hashlib.sha256(f'{library}\0{key}'.encode()).hexdigest()
        return self.path.parent / 'poster_cache' / f'{digest}.img'

    def cached_artwork(self, library, key):
        row = self.db.execute('SELECT a.mime,a.thumb,m.thumb FROM artwork a LEFT JOIN media m '
                              'ON m.library=a.library AND m.key=a.key '
                              'WHERE a.library=? AND a.key=?', (library, str(key))).fetchone()
        path = self.artwork_path(library, key)
        # A Plex scan can replace a thumbnail while the previous bytes still exist.
        return (path.read_bytes(), row[0]) if row and path.is_file() and (
            not row[2] or not row[1] or row[1] == row[2]) else None

    def store_artwork(self, library, key, data, mime, thumb=None):
        path = self.artwork_path(library, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.pending')
        temporary.write_bytes(data)
        os.replace(temporary, path)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO artwork VALUES (?, ?, ?, ?, ?)',
                            (library, str(key), mime, thumb, time.time()))

    def invalidate_artwork(self, library, key):
        with self.db:
            self.db.execute('DELETE FROM artwork WHERE library=? AND key=?', (library, str(key)))
        self.artwork_path(library, key).unlink(missing_ok=True)

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
