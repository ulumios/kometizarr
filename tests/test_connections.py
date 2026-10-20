import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import config


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'settings.json'
        self.patch = patch.object(config, 'SETTINGS_PATH', self.path)
        self.patch.start()
        self.env = patch.dict(os.environ, {'PLEX_URL': 'http://env:32400', 'PLEX_TOKEN': 'envtoken1234'}, clear=False)
        self.env.start()
        os.environ.pop('TMDB_API_KEY', None)

    def tearDown(self):
        self.env.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def save(self, connections):
        self.path.write_text(json.dumps({'connections': connections}))

    def test_saved_value_wins_over_environment(self):
        self.assertEqual(config.credential('plex_url'), 'http://env:32400')
        self.save({'plex_url': 'http://ui:32400', 'tmdb_api_key': ' abc '})
        self.assertEqual(config.credential('plex_url'), 'http://ui:32400')
        self.assertEqual(config.credential('plex_token'), 'envtoken1234')
        self.assertEqual(config.credential('tmdb_api_key'), 'abc')
        self.assertIsNone(config.credential('omdb_api_key'))

    def test_view_hides_secrets(self):
        self.save({'tmdb_api_key': 'secretvalue9876'})
        values, info = config.connections_view(config.load_settings())
        self.assertIsNone(values['tmdb_api_key'])
        self.assertIsNone(values['plex_token'])
        self.assertEqual(values['plex_url'], '')
        self.assertEqual(info['tmdb_api_key'], {'source': 'settings', 'env': 'TMDB_API_KEY', 'hint': '…9876'})
        self.assertEqual(info['plex_token']['source'], 'env')
        self.assertEqual(info['plex_url']['hint'], 'http://env:32400')
        self.assertNotIn('secretvalue', json.dumps([values, info]))

    def test_merge_keeps_removes_and_sets(self):
        stored = {'tmdb_api_key': 'old', 'omdb_api_key': 'keep'}
        merged = config.merge_connections(stored, {'tmdb_api_key': '', 'omdb_api_key': None,
                                                   'plex_url': ' http://x ', 'unknown': 'y'})
        self.assertEqual(merged, {'omdb_api_key': 'keep', 'plex_url': 'http://x'})


if __name__ == '__main__':
    unittest.main()
