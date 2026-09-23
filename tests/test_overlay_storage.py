"""Verify an interrupted Plex download cannot destroy a usable original."""

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.rating_overlay.poster_storage import capture_plex, paths, replace_image
from src.rating_overlay.backup_manager import PosterBackupManager
from src.rating_overlay.media_index import MediaIndex
from src.rating_overlay.task_queue import TaskQueue


def jpeg(color):
    data = io.BytesIO()
    Image.new('RGB', (20, 30), color).save(data, 'JPEG')
    return data.getvalue()


class OverlayStorageTest(unittest.TestCase):
    def test_failed_download_preserves_original_and_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            backups = PosterBackupManager(folder)
            item = SimpleNamespace(type='movie', title='Example', year=2020,
                                   ratingKey=17, posterUrl='http://plex/poster')
            original, overlay = paths(backups, 'Movies', item)
            replace_image(original, jpeg('red'))
            replace_image(overlay, jpeg('blue'))
            server = SimpleNamespace(_session=SimpleNamespace(get=lambda *_args, **_kwargs:
                                      SimpleNamespace(content=b'not an image', raise_for_status=lambda: None)))
            with self.assertRaises(Exception):
                capture_plex(backups, 'Movies', item, server, 'token')
            self.assertEqual(original.read_bytes(), jpeg('red'))
            self.assertEqual(overlay.read_bytes(), jpeg('blue'))

    def test_episodes_have_isolated_originals_and_conflicts_filter_by_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            index = MediaIndex(Path(folder) / 'index.db')
            show = SimpleNamespace(type='show', title='Same Name', ratingKey=10,
                                   parentRatingKey=None, year=2020, index=None)
            season = SimpleNamespace(type='season', title='Season 1', ratingKey=11,
                                     parentRatingKey=10, index=1)
            episode = SimpleNamespace(type='episode', title='Pilot', ratingKey=12,
                                      parentRatingKey=11, grandparentRatingKey=10,
                                      grandparentTitle='Same Name', parentIndex=1, index=1)
            unrelated = SimpleNamespace(type='show', title='Same Name', ratingKey=20,
                                        parentRatingKey=None, year=2026, index=None)
            index.replace_library('Shows', [show, season, episode, unrelated])
            index.record_conflict('Shows', episode, {'key': '12'})
            self.assertEqual(index.browse('Shows', conflicts_only=True)['total'], 1)
            self.assertEqual(index.browse('Shows', conflicts_only=True)['items'][0]['key'], '10')
            self.assertEqual(index.browse('Shows', parent_key=10, conflicts_only=True)['total'], 1)
            index.forget_conflict('Shows', 12)
            self.assertEqual(index.browse('Shows', conflicts_only=True)['total'], 0)
            index.close()

    def test_task_queue_keeps_progress_and_item_results(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / 'tasks.db')
            key = queue.add('process', {'library_name': 'Shows'})
            queue.claim()
            queue.update_progress(key, {'done': 1, 'total': 2}, {'12': 'gerendert'})
            queue.resume()
            resumed = queue.claim()
            self.assertEqual(resumed['results']['12'], 'gerendert')
            self.assertEqual(queue.list()[0]['progress']['done'], 1)
            queue.close()

    def test_poster_cache_survives_restart_and_can_be_invalidated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'index.db'
            index = MediaIndex(path)
            index.store_artwork('Shows', '12', jpeg('green'), 'image/jpeg', '/thumb/1')
            index.close()
            reopened = MediaIndex(path)
            self.assertEqual(reopened.cached_artwork('Shows', '12')[0], jpeg('green'))
            reopened.invalidate_artwork('Shows', '12')
            self.assertIsNone(reopened.cached_artwork('Shows', '12'))
            reopened.close()


if __name__ == '__main__':
    unittest.main()
