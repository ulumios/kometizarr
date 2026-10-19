import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.rating_overlay.task_queue import TaskQueue
from src.services import arr, config, overlay, tasks
from src.services.progress import progress

RADARR = {'eventType': 'Download', 'movie': {'title': 'Heat', 'imdbId': 'tt0113277', 'tmdbId': 949}}
SONARR = {'eventType': 'Download', 'series': {'title': 'Lost', 'tvdbId': 73739, 'imdbId': 'tt0411008'},
          'episodes': [{'seasonNumber': 1, 'episodeNumber': 2}]}


class ParseTest(unittest.TestCase):
    def test_reads_radarr_and_sonarr(self):
        self.assertEqual(arr.parse(RADARR)['ids']['imdb'], 'tt0113277')
        self.assertEqual(arr.parse(SONARR)['episodes'], [[1, 2]])
        self.assertIsNone(arr.parse({'eventType': 'Grab', 'movie': {}}))


class DelayedQueueTest(unittest.TestCase):
    def test_delayed_task_is_not_claimed_early(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = TaskQueue(Path(folder) / 't.db')
            queue.add('arr', {}, delay=60)
            self.assertIsNone(queue.claim())
            with patch('src.rating_overlay.task_queue.time.time', return_value=time.time() + 61):
                self.assertEqual(queue.claim()['kind'], 'arr')
            queue.close()


class ArrTaskTest(unittest.TestCase):
    def test_retries_until_plex_knows_the_title(self):
        task = {'id': 1, 'kind': 'arr', 'payload': {'target': arr.parse(RADARR), 'attempt': 1}}
        with patch.object(config, 'load_settings', return_value={'webhook': {}}), \
             patch.object(arr, 'resolve', return_value=None), \
             patch.object(tasks, 'enqueue', new_callable=AsyncMock, return_value=2) as enqueue:
            progress.reset()
            self.assertIsNone(asyncio.run(arr.arr_task(task)))
        kind, payload = enqueue.call_args.args
        self.assertEqual((kind, payload['attempt'], enqueue.call_args.kwargs['delay']), ('arr', 2, arr.RETRY_DELAY))

    def test_renders_found_title_and_episodes(self):
        task = {'id': 1, 'kind': 'arr', 'payload': {'target': arr.parse(SONARR), 'attempt': 1}}
        with patch.object(config, 'load_settings', return_value={'webhook': {}}), \
             patch.object(arr, 'resolve', return_value=('Serien', ['10', '12'])), \
             patch.object(overlay, 'run_overlay', new_callable=AsyncMock) as render:
            progress.reset()
            asyncio.run(arr.arr_task(task))
        request = render.call_args.args[0]
        self.assertEqual((request.library_name, request.rating_keys), ('Serien', ['10', '12']))

    def test_resolve_finds_episode_by_number(self):
        from plexapi.exceptions import NotFound
        show = SimpleNamespace(ratingKey=10, episode=lambda season, episode: SimpleNamespace(ratingKey=12))
        def get_guid(guid):
            if guid != 'imdb://tt0411008':
                raise NotFound('no')
            return show
        library = SimpleNamespace(type='show', title='Serien', getGuid=get_guid)
        server = SimpleNamespace(library=SimpleNamespace(sections=lambda: [library]))
        with patch.object(config, 'plex_server', return_value=server):
            self.assertEqual(arr.resolve(arr.parse(SONARR), []), ('Serien', ['10', '12']))
            self.assertIsNone(arr.resolve(arr.parse(RADARR), []))  # no movie library


class TokenTest(unittest.TestCase):
    def test_token_required_only_when_configured(self):
        from web.backend.main import app
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as folder, \
             patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(Path(folder) / 't.db')):
            with patch.object(config, 'load_settings', return_value={'webhook': {'enabled': True, 'token': 's3cret'}}):
                self.assertEqual(client.post('/webhook/arr', json=RADARR).status_code, 403)
                self.assertEqual(client.post('/webhook/arr?token=wrong', json=RADARR).status_code, 403)
                ok = client.post('/webhook/arr?token=s3cret', json=RADARR)
                self.assertEqual(ok.json()['status'], 'queued')
                self.assertEqual(client.post('/webhook/plex', data={'payload': '{}'}).status_code, 403)
            with patch.object(config, 'load_settings', return_value={'webhook': {'enabled': True}}):
                self.assertEqual(client.post('/webhook/arr', json={'eventType': 'Test', 'movie': {}}).status_code, 200)
            queued = tasks.with_tasks('fetch', ok.json()['task_id'])
            self.assertGreater(queued['run_after'], time.time() + 60)


if __name__ == '__main__':
    unittest.main()
