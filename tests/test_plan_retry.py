import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from src.rating_overlay.task_queue import TaskQueue
from src.services import config, overlay, tasks
from src.services.models import ProcessRequest
from src.services.progress import progress


class PlanTest(unittest.TestCase):
    def test_preview_decides_but_changes_nothing(self):
        new = SimpleNamespace(type='movie', title='Neu', ratingKey=1, year=2000, labels=[], guids=[])
        same = SimpleNamespace(type='movie', title='Gleich', ratingKey=2, year=2000, labels=[], guids=[])
        kometa = SimpleNamespace(type='movie', title='Kometa', ratingKey=3, year=2000, guids=[],
                                 labels=[SimpleNamespace(tag='Overlay')])
        manager = Mock(library=SimpleNamespace(all=lambda: [new, same, kometa], type='movie'), library_name='Movies')
        manager.collect_inputs.return_value = {'problem': None, 'ratings': {'imdb': 7}}
        manager.render_hash.return_value = 'h'
        manager.backup_manager.has_overlay.side_effect = lambda _lib, item: item.ratingKey == 2
        rows = {2: {'render_hash': 'h'}}
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'original.jpg'
            with patch.object(config, 'create_manager', return_value=manager), \
                 patch.object(config, 'load_settings', return_value={'imdb_direct': {}}), \
                 patch.object(overlay, 'item_row', side_effect=lambda _lib, item: rows.get(item.ratingKey)), \
                 patch.object(overlay, 'mark_item') as mark, \
                 patch('src.rating_overlay.poster_storage.paths', return_value=(original, original)), \
                 patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
                 patch('src.rating_overlay.api_cache.ApiCache'), \
                 patch('src.services.conflicts.remember') as remember:
                queue.return_value.state.return_value = 'none'
                progress.reset()
                asyncio.run(overlay.run_overlay(ProcessRequest(library_name='Movies', plan_only=True,
                                                               record_results=True)))
        manager.process_movie.assert_not_called()
        mark.assert_not_called()
        remember.assert_not_called()
        self.assertEqual(progress.results, {'1': 'würde rendern: neu', '2': 'unverändert',
                                            '3': 'Kometa-Konflikt: Reset erforderlich'})
        self.assertEqual(progress.extra['summary']['unverändert'], 1)
        self.assertEqual((progress.success, progress.skipped), (1, 2))


class RetryTest(unittest.TestCase):
    def test_follow_up_limits_to_failed_keys(self):
        task = {'kind': 'webhook', 'payload': {'library': 'Movies', 'key': '5', 'title': 'X'}}
        self.assertEqual(tasks.follow_up(task, ['5']), ('process', {'library_name': 'Movies', 'rating_keys': ['5']}))
        with self.assertRaises(ValueError):
            tasks.follow_up({'kind': 'imdb', 'payload': {}}, ['1'])

    def test_retry_endpoint_queues_failed_items_only(self):
        from web.backend.main import app
        with tempfile.TemporaryDirectory() as folder, \
             patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(Path(folder) / 't.db')):
            first = tasks.with_tasks('add', 'process', {'library_name': 'Movies', 'force': True})
            tasks.with_tasks('claim')
            tasks.with_tasks('update_progress', first, {'failed_keys': ['7', '9']})
            tasks.with_tasks('finish', first, '2 Poster fehlgeschlagen')
            client = TestClient(app)
            response = client.post(f'/api/tasks/{first}/retry')
            self.assertEqual(response.status_code, 200)
            queued = tasks.with_tasks('fetch', response.json()['task_id'])
            self.assertEqual(queued['payload']['rating_keys'], ['7', '9'])
            self.assertTrue(queued['payload']['force'])
            self.assertEqual(client.post('/api/tasks/999/retry').status_code, 404)


    def test_kometa_reset_endpoint_queues_skipped_items_with_reset(self):
        from web.backend.main import app
        with tempfile.TemporaryDirectory() as folder, \
             patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(Path(folder) / 't.db')):
            first = tasks.with_tasks('add', 'selected_imdb', {'library': 'Movies', 'request': {}})
            tasks.with_tasks('claim')
            tasks.with_tasks('update_progress', first, {'kometa_keys': {'Movies': ['4', '5']}})
            tasks.with_tasks('finish', first, None)
            client = TestClient(app)
            response = client.post(f'/api/tasks/{first}/kometa-reset')
            self.assertEqual((response.status_code, response.json()['items']), (200, 2))
            payload = tasks.with_tasks('fetch', response.json()['task_id'])['payload']
            self.assertEqual((payload['library_name'], payload['rating_keys'], payload['reset_kometa'],
                              payload['operation']), ('Movies', ['4', '5'], True, 'imdb_overlay'))
            empty = tasks.with_tasks('add', 'process', {'library_name': 'Movies'})
            self.assertEqual(client.post(f'/api/tasks/{empty}/kometa-reset').status_code, 400)

    def test_progress_remembers_kometa_skips_per_library(self):
        progress.reset(task_id=1, kind='process')
        progress.kometa_skipped('Filme', 3)
        progress.kometa_skipped('Filme', 3)
        progress.kometa_skipped('Serien', 8)
        self.assertEqual(progress.snapshot()['kometa_keys'], {'Filme': ['3'], 'Serien': ['8']})
        progress.reset()


class RecentTest(unittest.TestCase):
    def test_recently_added_or_updated_items(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        items = [SimpleNamespace(title='neu', addedAt=now - timedelta(days=2), updatedAt=None),
                 SimpleNamespace(title='upgrade', addedAt=now - timedelta(days=300), updatedAt=now - timedelta(days=5)),
                 SimpleNamespace(title='alt', addedAt=now - timedelta(days=300), updatedAt=now - timedelta(days=30))]
        self.assertEqual([item.title for item in overlay.recently_changed(items, 14)], ['neu', 'upgrade'])

if __name__ == '__main__':
    unittest.main()
