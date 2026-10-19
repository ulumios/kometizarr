import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.rating_overlay.task_queue import TaskQueue
from src.services import tasks
from src.services.progress import RunProgress, progress


class RunProgressTest(unittest.TestCase):
    def test_nested_render_inside_imdb_task_keeps_task_identity(self):
        run = RunProgress()
        run.reset(5, 'imdb', phase='IMDb-Datensatz laden')
        run.extra.update(scanned=10, rendered=0, failed=0)
        run.percent = 85
        run.begin_items('process', total=4, library='Movies')
        run.done, run.success = 2, 2
        self.assertTrue(run.processing_view()['is_processing'])
        imdb = run.imdb_view()
        self.assertEqual((imdb['is_running'], imdb['rendered'], imdb['scanned']), (True, 2, 10))
        self.assertGreater(imdb['percent'], 85)
        run.end_items()
        run.finish()
        self.assertFalse(run.processing_view()['is_processing'])
        self.assertFalse(run.imdb_view()['is_running'])

    def test_restore_view_maps_success_to_restored(self):
        run = RunProgress()
        run.reset(1, 'restore')
        run.begin_items('restore', total=3)
        run.count('success')
        run.count('skipped')
        view = run.restore_view()
        self.assertEqual((view['is_restoring'], view['restored'], view['skipped']), (True, 1, 1))
        run.end_items()  # the final update after the loop must still be a restore view
        self.assertEqual(run.live_view()['is_restoring'], False)
        self.assertEqual(run.live_view()['restored'], 1)

    def test_finished_conflict_task_stays_visible(self):
        run = RunProgress()
        run.reset(2, 'conflict', phase='Kometa-Label entfernen')
        run.total = 1
        run.count('success', '12', 'Label entfernt')
        run.finish()
        run.reset(3, 'process')
        view = run.conflict_view()
        self.assertEqual((view['is_running'], view['resolved'], view['results']), (False, 1, {'12': 'Label entfernt'}))


class WorkerTest(unittest.TestCase):
    def test_task_progress_and_results_are_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'tasks.db'

            async def fake(task):
                progress.begin_items('process', total=2, library='Movies')
                progress.done = 2
                progress.count('success', '1', 'gerendert')
                progress.count('failed', '2', 'kaputt')
                return 'einer fehlgeschlagen'

            with patch.dict(tasks.HANDLERS, {'fake': fake}), \
                 patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(db)):
                task_id = asyncio.run(tasks.enqueue('fake', {'library_name': 'Movies'}))
                task = tasks.with_tasks('claim')
                self.assertEqual(asyncio.run(tasks.run_task(task)), 'einer fehlgeschlagen')
                stored = tasks.with_tasks('list')[0]
            self.assertEqual(stored['id'], task_id)
            self.assertEqual(stored['status'], 'failed')
            self.assertEqual(stored['progress']['success'], 1)
            self.assertEqual(stored['results'], {'1': 'gerendert', '2': 'kaputt'})
            self.assertFalse(progress.running)


class StatusEndpointsTest(unittest.TestCase):
    def test_all_status_endpoints_answer(self):
        from web.backend.main import app
        with tempfile.TemporaryDirectory() as folder, \
             patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(Path(folder) / 't.db')):
            client = TestClient(app)  # no context manager: the worker is not started
            for path in ('/api/status', '/api/restore/status', '/api/progress', '/api/imdb-sync/status',
                         '/api/kometa/conflicts/status', '/api/fetch-fresh-posters/status',
                         '/api/library-scan/status', '/api/tasks', '/'):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
            self.assertIn('is_processing', client.get('/api/status').json())
            self.assertIn('is_restoring', client.get('/api/restore/status').json())


if __name__ == '__main__':
    unittest.main()
