"""Local IMDb rating cache sourced from IMDb's daily non-commercial ratings dataset."""

import csv
import gzip
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


RATINGS_URL = 'https://datasets.imdbws.com/title.ratings.tsv.gz'


class ImdbRatingCache:
    def __init__(self, path='/backups/imdb_ratings.sqlite3'):
        self.path = Path(path)
        self.dataset_path = self.path.with_suffix('.tsv.gz')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS ratings (imdb_id TEXT PRIMARY KEY, rating REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS applied (library TEXT NOT NULL, rating_key TEXT NOT NULL, imdb_id TEXT NOT NULL, rating REAL NOT NULL, PRIMARY KEY (library, rating_key))')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def ratings(self, ids):
        ids = set(ids)
        if not ids:
            return {}
        # SQLite has a bound parameter limit; use batches.
        result = {}
        ordered = sorted(ids)
        for start in range(0, len(ordered), 500):
            batch = ordered[start:start + 500]
            slots = ','.join('?' for _ in batch)
            result.update(self.db.execute(f'SELECT imdb_id, rating FROM ratings WHERE imdb_id IN ({slots})', batch))
        return result

    def applied(self, library, rating_key):
        return self.db.execute('SELECT imdb_id, rating FROM applied WHERE library=? AND rating_key=?',
                               (library, str(rating_key))).fetchone()

    def mark_applied(self, library, rating_key, imdb_id, rating):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO applied VALUES (?, ?, ?, ?)',
                            (library, str(rating_key), imdb_id, rating))

    def updated_at(self):
        row = self.db.execute("SELECT value FROM meta WHERE name='updated_at'").fetchone()
        return row[0] if row else None

    def refresh(self, ids):
        """Reuse a daily dataset download; atomically cache the requested ratings."""
        wanted = set(ids)
        found = {}
        fresh = self.dataset_path.exists() and time.time() - self.dataset_path.stat().st_mtime < 86400
        source = self.dataset_path if fresh else self.dataset_path.with_suffix('.pending.gz')
        try:
            if not fresh:
                with requests.get(RATINGS_URL, stream=True, timeout=(20, 120)) as response:
                    response.raise_for_status()
                    response.raw.decode_content = False
                    with source.open('wb') as destination:
                        shutil.copyfileobj(response.raw, destination)
            with gzip.open(source, 'rt', encoding='utf-8') as stream:
                rows = csv.DictReader(stream, delimiter='\t')
                if not {'tconst', 'averageRating'}.issubset(rows.fieldnames or []):
                    raise ValueError('IMDb ratings dataset has an unexpected format')
                for row in rows:
                    if row['tconst'] in wanted:
                        found[row['tconst']] = float(row['averageRating'])
            if not fresh:
                os.replace(source, self.dataset_path)
        finally:
            if not fresh:
                source.unlink(missing_ok=True)
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO ratings VALUES (?, ?)', found.items())
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)',
                            ('updated_at', datetime.now(timezone.utc).isoformat()))
        return found
