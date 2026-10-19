import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.rating_overlay.task_queue import TaskQueue
from src.services import config, health


class HealthTest(unittest.TestCase):
    def test_report_marks_failures_without_raising(self):
        response = SimpleNamespace(ok=False, status_code=401, json=lambda: {'Response': 'False', 'Error': 'Invalid API key!'})
        env = {'PLEX_URL': 'http://plex', 'PLEX_TOKEN': 't', 'TMDB_API_KEY': 'bad', 'OMDB_API_KEY': 'bad'}
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict('os.environ', env, clear=False), \
             patch.dict('os.environ', {'MDBLIST_API_KEY': ''}), \
             patch.object(config, 'BACKUP_DIR', Path(folder)), \
             patch.object(config, 'load_settings', return_value={}), \
             patch.object(config, 'plex_server', side_effect=ConnectionError('refused')), \
             patch('src.services.health.requests.get', return_value=response), \
             patch('src.rating_overlay.task_queue.TaskQueue', side_effect=lambda: TaskQueue(Path(folder) / 't.db')):
            data = health.report(refresh=True)
        states = {check['name']: check['state'] for check in data['checks']}
        self.assertEqual(states['Plex'], 'error')
        self.assertEqual(states['TMDB'], 'error')
        self.assertEqual(states['OMDb'], 'error')
        self.assertEqual(states['MDBList'], 'missing')
        self.assertEqual(states['IMDb-Datensatz'], 'missing')
        self.assertEqual(states['Speicherplatz /backups'], 'ok')
        self.assertEqual(data['queue']['queued'], 0)

    def test_webhook_calls_are_listed(self):
        from web.backend.main import app
        health.webhook_events.clear()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(config, 'load_settings', return_value={'webhook': {'enabled': False}}):
            client = TestClient(app)
            client.post('/webhook/plex', data={'payload': '{"event": "library.new", "Metadata": {"title": "X", "librarySectionTitle": "Movies"}}'})
        self.assertEqual(health.webhook_events[0]['status'], 'ignoriert: ausgeschaltet')
        self.assertEqual(health.webhook_events[0]['title'], 'X')


if __name__ == '__main__':
    unittest.main()
