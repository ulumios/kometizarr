"""One row of Kometizarr state per Plex item (see docs/KONZEPT.md, section 1)."""

import json
import sqlite3
import time
from pathlib import Path

from src.rating_overlay.data_paths import data_file

COLUMNS = ('type', 'title', 'year', 'series', 'season', 'episode', 'backup_id',
           'original_source', 'original_hash', 'render_hash', 'uploaded_thumb',
           'uploaded_poster', 'status', 'kometa_state', 'manual_identity', 'reason',
           'attempts', 'rendered_at', 'updated_at')


class ItemState:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_file('media_index.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS item_state (
            library TEXT NOT NULL, rating_key TEXT NOT NULL,
            type TEXT, title TEXT, year INTEGER, series TEXT, season INTEGER, episode INTEGER,
            backup_id TEXT, original_source TEXT, original_hash TEXT, render_hash TEXT,
            uploaded_thumb TEXT, uploaded_poster TEXT, status TEXT,
            kometa_state TEXT NOT NULL DEFAULT 'none', manual_identity TEXT, reason TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, rendered_at REAL, updated_at REAL,
            PRIMARY KEY (library, rating_key))''')
        self.db.execute('CREATE INDEX IF NOT EXISTS item_state_status ON item_state(library, status)')
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def get(self, library, rating_key):
        row = self.db.execute(f'SELECT {",".join(COLUMNS)} FROM item_state WHERE library=? AND rating_key=?',
                              (library, str(rating_key))).fetchone()
        return dict(zip(COLUMNS, row)) if row else None

    def update(self, library, item_or_key, **fields):
        """Upsert the given fields; descriptive columns are refreshed from a Plex item."""
        unknown = set(fields) - set(COLUMNS)
        if unknown:
            raise ValueError(f'Unknown item_state fields: {sorted(unknown)}')
        if not isinstance(item_or_key, (str, int)):
            item = item_or_key
            key = str(item.ratingKey)
            described = {'type': getattr(item, 'type', None), 'title': getattr(item, 'title', None),
                         'year': getattr(item, 'year', None)}
            if described['type'] == 'episode':
                described.update(series=getattr(item, 'grandparentTitle', None),
                                 season=getattr(item, 'parentIndex', None),
                                 episode=getattr(item, 'index', None))
            fields = {**{k: v for k, v in described.items() if v is not None}, **fields}
        else:
            key = str(item_or_key)
        if isinstance(fields.get('manual_identity'), dict):
            fields['manual_identity'] = json.dumps(fields['manual_identity'], sort_keys=True)
        fields['updated_at'] = time.time()
        names = list(fields)
        with self.db:
            self.db.execute(
                f'INSERT INTO item_state (library, rating_key, {",".join(names)}) '
                f'VALUES (?, ?, {",".join("?" for _ in names)}) '
                f'ON CONFLICT(library, rating_key) DO UPDATE SET '
                + ','.join(f'{name}=excluded.{name}' for name in names),
                (library, key, *fields.values()))

    def forget(self, library, rating_key):
        with self.db:
            self.db.execute('DELETE FROM item_state WHERE library=? AND rating_key=?',
                            (library, str(rating_key)))

    def keys(self, library, **filters):
        clause = ''.join(f' AND {name}=?' for name in filters)
        if set(filters) - set(COLUMNS):
            raise ValueError('Unknown filter')
        return [row[0] for row in self.db.execute(
            f'SELECT rating_key FROM item_state WHERE library=?{clause}', (library, *filters.values()))]

    def rows(self, library):
        return [dict(zip(('rating_key',) + COLUMNS, row)) for row in self.db.execute(
            f'SELECT rating_key,{",".join(COLUMNS)} FROM item_state WHERE library=?', (library,))]

    def migrate(self, manual_queue_path=None):
        """One-time import of the older origins table and the manual Kometa JSON queue."""
        with self.db:
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='origins'").fetchone():
                for library, key, source, poster_id, updated in self.db.execute(
                        'SELECT library,key,source,poster_id,updated_at FROM origins').fetchall():
                    self.db.execute(
                        'INSERT INTO item_state (library, rating_key, original_source, updated_at) '
                        'VALUES (?, ?, ?, ?) ON CONFLICT(library, rating_key) DO UPDATE SET '
                        'original_source=coalesce(item_state.original_source, excluded.original_source)',
                        (library, key, source, updated))
                self.db.execute('DROP TABLE origins')
        if manual_queue_path and Path(manual_queue_path).is_file():
            try:
                pending = json.loads(Path(manual_queue_path).read_text())
            except (OSError, ValueError):
                pending = {}
            for compound, identity in pending.items():
                library, _, key = compound.rpartition(':')
                if library and key:
                    self.update(library, key, kometa_state='manual_pending', manual_identity=identity)
            Path(manual_queue_path).rename(Path(manual_queue_path).with_suffix('.migrated'))
