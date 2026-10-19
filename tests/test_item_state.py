import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.rating_overlay import poster_storage
from src.rating_overlay.backup_manager import PosterBackupManager
from src.rating_overlay.item_state import ItemState
from src.rating_overlay.poster_storage import backup_id, paths


def guid(value):
    return SimpleNamespace(id=value)


def jpeg(color):
    data = io.BytesIO()
    Image.new('RGB', (4, 6), color).save(data, 'JPEG')
    return data.getvalue()


class BackupLayoutTest(unittest.TestCase):
    def setUp(self):
        poster_storage._show_ids.clear()

    def test_backup_id_prefers_imdb_then_tmdb_then_plex(self):
        self.assertEqual(backup_id(SimpleNamespace(ratingKey=1, guids=[guid('tmdb://603'), guid('imdb://tt0133093')])), 'tt0133093')
        self.assertEqual(backup_id(SimpleNamespace(ratingKey=1, guids=[guid('tmdb://603')])), 'tmdb-603')
        self.assertEqual(backup_id(SimpleNamespace(ratingKey=7, guids=[])), 'plex-7')

    def test_movie_title_backup_moves_into_imdb_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            backups = PosterBackupManager(folder)
            legacy = Path(folder) / 'Movies' / 'The Matrix (1999)'
            legacy.mkdir(parents=True)
            (legacy / 'poster_original.jpg').write_bytes(jpeg('red'))
            (legacy / 'poster_overlay.jpg').write_bytes(jpeg('blue'))
            (legacy / 'metadata.json').write_text(json.dumps({'rating_key': 5}))
            movie = SimpleNamespace(type='movie', title='The Matrix', year=1999, ratingKey=5,
                                    guids=[guid('imdb://tt0133093')])
            original, overlay = paths(backups, 'Movies', movie)
            self.assertEqual(original, Path(folder) / 'Movies' / 'tt0133093' / 'original.jpg')
            self.assertEqual(original.read_bytes(), jpeg('red'))
            self.assertEqual(overlay.read_bytes(), jpeg('blue'))
            self.assertFalse(legacy.exists())
            self.assertTrue(backups.has_overlay('Movies', movie))

    def test_same_title_backup_of_other_item_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            backups = PosterBackupManager(folder)
            legacy = Path(folder) / 'Movies' / 'Heat'
            legacy.mkdir(parents=True)
            (legacy / 'poster_original.jpg').write_bytes(jpeg('red'))
            (legacy / 'metadata.json').write_text(json.dumps({'rating_key': 99}))
            movie = SimpleNamespace(type='movie', title='Heat', year=None, ratingKey=5, guids=[])
            original, _ = paths(backups, 'Movies', movie)
            self.assertFalse(original.exists())
            self.assertTrue((legacy / 'poster_original.jpg').exists())

    def test_episode_backup_lives_in_show_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            backups = PosterBackupManager(folder)
            legacy = Path(folder) / 'Shows' / 'Lost (2004)'
            legacy.mkdir(parents=True)
            (legacy / 'S01E02-poster_original.jpg').write_bytes(jpeg('green'))
            show = SimpleNamespace(guids=[guid('imdb://tt0411008')])
            episode = SimpleNamespace(type='episode', title='Pilot 2', ratingKey=12, grandparentRatingKey=10,
                                      grandparentTitle='Lost', grandparentYear=2004, parentIndex=1,
                                      index=2, guids=[], show=lambda: show)
            original, _ = paths(backups, 'Shows', episode)
            self.assertEqual(original, Path(folder) / 'Shows' / 'tt0411008' / 'S01E02' / 'original.jpg')
            self.assertEqual(original.read_bytes(), jpeg('green'))

    def test_restore_uploads_original_and_drops_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            backups = PosterBackupManager(folder)
            uploads = []
            movie = SimpleNamespace(type='movie', title='X', year=2000, ratingKey=3, guids=[],
                                    uploadPoster=lambda filepath: uploads.append(filepath))
            original, overlay = paths(backups, 'Movies', movie)
            original.parent.mkdir(parents=True)
            original.write_bytes(jpeg('red'))
            overlay.write_bytes(jpeg('blue'))
            self.assertTrue(backups.restore_original('Movies', movie))
            self.assertEqual(uploads, [str(original)])
            self.assertFalse(overlay.exists())


class ItemStateTest(unittest.TestCase):
    def test_update_merges_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            with ItemState(Path(folder) / 'state.db') as store:
                item = SimpleNamespace(ratingKey=4, type='movie', title='Heat', year=1995)
                store.update('Movies', item, status='rendered')
                store.update('Movies', 4, reason='x')
                row = store.get('Movies', 4)
                self.assertEqual((row['title'], row['status'], row['reason']), ('Heat', 'rendered', 'x'))
                with self.assertRaises(ValueError):
                    store.update('Movies', 4, bogus=1)

    def test_migrates_origins_table_and_manual_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'state.db'
            legacy = sqlite3.connect(db)
            legacy.execute('CREATE TABLE origins (library TEXT, key TEXT, source TEXT, poster_id TEXT, updated_at REAL)')
            legacy.execute("INSERT INTO origins VALUES ('Movies', '4', 'agent', '', 1)")
            legacy.commit()
            legacy.close()
            queue = Path(folder) / 'kometa_manual_pending.json'
            queue.write_text(json.dumps({'Shows:12': {'thumb': '/t/1', 'poster': None}}))
            with ItemState(db) as store:
                store.migrate(queue)
                store.migrate(queue)  # idempotent
                self.assertEqual(store.get('Movies', 4)['original_source'], 'agent')
                self.assertEqual(store.get('Shows', 12)['kometa_state'], 'manual_pending')
            self.assertFalse(queue.exists())


if __name__ == '__main__':
    unittest.main()
