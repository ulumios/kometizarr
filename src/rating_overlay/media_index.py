"""Persistent read index for Plex library browsing and conflict snapshots."""

import json
import logging
import sqlite3
import time
import hashlib
import os
from pathlib import Path

from plexapi.exceptions import NotFound

from src.rating_overlay.data_paths import data_file

logger = logging.getLogger(__name__)


class MediaIndex:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_file('media_index.sqlite3')
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
        ''')
        # Overlay flags for the "ohne Overlay" filter; NULL until the library was scanned.
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(media)')}
        for name in ('has_overlay', 'kometa_label'):
            if name not in columns:
                self.db.execute(f'ALTER TABLE media ADD COLUMN {name} INTEGER')
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

    MEDIA_COLUMNS = ('library, key, title, type, parent_key, year, item_index, series, season, thumb, '
                     'has_overlay, kometa_label')

    def replace_library(self, library, items, progress=None, flags=None):
        """``flags(item)`` returns (has_overlay, kometa_label) for the overlay filter."""
        rows = []
        for position, item in enumerate(items, 1):
            try:
                overlay, label = flags(item) if flags else (None, None)
                rows.append((library, str(item.ratingKey), item.title, item.type,
                             str(getattr(item, 'parentRatingKey', '') or '') or None,
                             getattr(item, 'year', None), getattr(item, 'index', None),
                             getattr(item, 'grandparentTitle', None), getattr(item, 'parentIndex', None),
                             getattr(item, 'thumb', None), overlay, label))
            except NotFound:
                logger.info('Plex item disappeared while indexing %s: %s', library, item.ratingKey)
            if progress is not None and (position % 50 == 0 or position == len(items)):
                progress.update(scanned=position, total=len(items), phase='Speichere Bibliothek')
        with self.db:
            self.db.execute('DELETE FROM media WHERE library=?', (library,))
            self.db.executemany(f'INSERT INTO media ({self.MEDIA_COLUMNS}) VALUES ({",".join("?" * 12)})', rows)
            self.db.execute('DELETE FROM conflicts WHERE library=? AND key NOT IN '
                            '(SELECT key FROM media WHERE library=?)', (library, library))
            self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, NULL)',
                            (library, 'browse', time.time()))
            if flags:
                self.db.execute('INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, NULL)',
                                (library, 'overlay_flags', time.time()))

    def browse(self, library, parent_key=None, episodes=False, q='', page=1, page_size=60,
               conflicts_only=False, missing_overlay=False, only_keys=None, errors_only=False):
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
        if missing_overlay:
            # Rendered items have no overlay flag of 0; Kometa items (label or recorded conflict) are hidden.
            missing = ("has_overlay=0 AND coalesce(kometa_label,0)=0 AND type IN ('movie','show','episode') "
                       "AND key NOT IN (SELECT key FROM conflicts WHERE library=?)")
            episodes_missing = (f"SELECT parent_key FROM media WHERE library=? AND type='episode' AND {missing}")
            if parent_row and parent_row[0] == 'show':
                where += f' AND key IN ({episodes_missing})'  # seasons with an episode lacking an overlay
                params.extend([library, library])
            elif parent_row or episodes:
                where += f' AND {missing}'
                params.append(library)
            else:
                # Top level: the movie/show itself, or a show with an episode lacking an overlay
                where += (f" AND (({missing}) OR (type='show' AND key IN (SELECT parent_key FROM media "
                          f"WHERE library=? AND type='season' AND key IN ({episodes_missing}))))")
                params.extend([library, library, library, library])
            select = 'SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where
        if errors_only:
            # Items whose last run failed (item_state, same database); shows and seasons lead to them
            has_state = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_state'").fetchone()
            failed = "SELECT rating_key FROM item_state WHERE library=? AND status='failed'" if has_state else 'SELECT NULL WHERE 0'
            failed_params = [library] if has_state else []
            episodes_failed = f"SELECT parent_key FROM media WHERE library=? AND type='episode' AND key IN ({failed})"
            if parent_row and parent_row[0] == 'show':
                where += f' AND (key IN ({failed}) OR key IN ({episodes_failed}))'
                params.extend([*failed_params, library, *failed_params])
            elif parent_row or episodes:
                where += f' AND key IN ({failed})'
                params.extend(failed_params)
            else:
                where += (f" AND (key IN ({failed}) OR (type='show' AND key IN (SELECT parent_key FROM media "
                          f"WHERE library=? AND type='season' AND (key IN ({failed}) OR key IN ({episodes_failed})))))")
                params.extend([*failed_params, library, *failed_params, library, *failed_params])
            select = 'SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where
        if only_keys is not None:
            # Results of a task: the touched items and the shows/seasons leading to them
            where += ' AND key IN (SELECT value FROM json_each(?))'
            params.append(json.dumps(sorted(only_keys)))
            select = 'SELECT key, title, type, year, item_index, series, season FROM media WHERE ' + where
        total = self.db.execute('SELECT count(*) FROM media WHERE ' + where, params).fetchone()[0]
        rows = self.db.execute(select + order + ' LIMIT ? OFFSET ?',
                               [*params, page_size, (page - 1) * page_size]).fetchall()
        return {'total': total, 'page': page, 'items': [dict(zip(
            ('key', 'title', 'type', 'year', 'index', 'series', 'season'), row)) for row in rows]}

    def errors(self, library, keys):
        """{key: reason} of the given items whose last run failed."""
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_state'").fetchone():
            return {}
        return dict(self.db.execute(
            "SELECT rating_key, coalesce(reason, 'Fehler') FROM item_state WHERE library=? AND status='failed' "
            "AND rating_key IN (SELECT value FROM json_each(?))", (library, json.dumps([str(key) for key in keys]))))

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

    def upsert_item(self, library, item, has_overlay=0, kometa_label=None):
        values = (library, str(item.ratingKey), item.title, item.type,
                  str(getattr(item, 'parentRatingKey', '') or '') or None,
                  getattr(item, 'year', None), getattr(item, 'index', None),
                  getattr(item, 'grandparentTitle', None), getattr(item, 'parentIndex', None),
                  getattr(item, 'thumb', None), has_overlay, kometa_label)
        with self.db:
            self.db.execute(f'INSERT OR REPLACE INTO media ({self.MEDIA_COLUMNS}) VALUES ({",".join("?" * 12)})', values)

    def set_flags(self, library, rating_key, has_overlay=None, kometa_label=None):
        """Keep the overlay filter current after renders, restores and Kometa actions."""
        updates = {name: int(value) for name, value in (('has_overlay', has_overlay), ('kometa_label', kometa_label))
                   if value is not None}
        if not updates:
            return
        with self.db:
            self.db.execute(f'UPDATE media SET {", ".join(f"{name}=?" for name in updates)} WHERE library=? AND key=?',
                            (*updates.values(), library, str(rating_key)))

    def describe(self, keys):
        """Index rows of rating keys in any library (Plex keys are unique per server)."""
        keys = [str(key) for key in keys]
        rows = self.db.execute(
            'SELECT library, key, title, type, year, item_index, series, season, parent_key FROM media '
            'WHERE key IN (SELECT value FROM json_each(?))', (json.dumps(keys),))
        found = {row[1]: dict(zip(('library', 'key', 'title', 'type', 'year', 'index', 'series', 'season',
                                   'parent_key'), row)) for row in rows}
        return [found[key] for key in keys if key in found]

    def ancestors(self, library, key):
        """Show and season above an item, top first, as browse entries."""
        chain, current = [], str(key)
        for _ in range(3):
            row = self.db.execute('SELECT parent_key FROM media WHERE library=? AND key=?', (library, current)).fetchone()
            if not row or not row[0]:
                break
            current = row[0]
            parent = self.db.execute('SELECT key, title, type, item_index FROM media WHERE library=? AND key=?',
                                     (library, current)).fetchone()
            if not parent:
                break
            chain.insert(0, dict(zip(('key', 'title', 'type', 'index'), parent)))
        return chain

    def related_keys(self, library, keys):
        """The keys plus their show/season and, for a selected show or season, everything below it."""
        result = {str(key) for key in keys}
        frontier = set(result)
        for _ in range(2):  # show -> season -> episode
            frontier = {row[0] for row in self.db.execute(
                'SELECT key FROM media WHERE library=? AND parent_key IN (SELECT value FROM json_each(?))',
                (library, json.dumps(sorted(frontier))))} - result
            result |= frontier
        for key in list(keys):
            result |= {entry['key'] for entry in self.ancestors(library, key)}
        return result

    def kometa_keys(self, library, keys):
        """Selected items (episodes of selected seasons included) that carry a Kometa overlay
        and no Kometizarr overlay, i.e. the ones a run would skip for Kometa."""
        keys = [str(key) for key in keys]
        if not keys:
            return []
        marks = ','.join('?' * len(keys))
        rows = self.db.execute(
            f"""SELECT key FROM media WHERE library=? AND (key IN ({marks})
                    OR (type='episode' AND parent_key IN ({marks})))
                AND coalesce(has_overlay,0)=0
                AND (kometa_label=1 OR key IN (SELECT key FROM conflicts WHERE library=?))""",
            (library, *keys, *keys, library))
        return [row[0] for row in rows]

    def flags_ready(self, library):
        return bool(self.snapshot(library, 'overlay_flags')[0])
