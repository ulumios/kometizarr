import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services import imdb, library_index, overlay
from src.services.progress import progress
from web.backend.routes import library as library_routes


class PosterProxyTest(unittest.TestCase):
    def test_poster_uses_plex_token_and_returns_image(self):
        key = 983761
        item = SimpleNamespace(thumb=f'/library/metadata/{key}/thumb/42', librarySectionID=1)
        library = SimpleNamespace(key=1, fetchItem=lambda _: item)
        captured = {}

        def get(url, **kwargs):
            captured.update(url=url, **kwargs)
            return SimpleNamespace(content=b'jpeg bytes', headers={'Content-Type': 'image/jpeg'},
                                   raise_for_status=lambda: None)

        server = SimpleNamespace(library=SimpleNamespace(section=lambda _: library),
                                 url=lambda path: 'http://plex:32400' + path,
                                 _session=SimpleNamespace(get=get))
        library_index.browse_image_cache.clear()
        from src.rating_overlay.media_index import MediaIndex
        with tempfile.TemporaryDirectory() as folder, \
             patch('src.rating_overlay.media_index.MediaIndex',
                   side_effect=lambda: MediaIndex(Path(folder) / 'index.sqlite3')), \
             patch('plexapi.server.PlexServer', return_value=server), patch.dict(os.environ, {'PLEX_TOKEN': 'secret'}):
            result = asyncio.run(library_routes.browse_poster('Series', key))
        self.assertEqual(result.body, b'jpeg bytes')
        self.assertEqual(captured['headers'], {'X-Plex-Token': 'secret'})

    def test_rating_only_reports_change_without_rendering_poster(self):
        class Cache:
            def ratings(self, _ids):
                return {'tt123': 7.4}

            def refresh(self, _ids, _progress=None):
                return {'tt123': 7.5}

            def updated_at(self):
                return '2026-09-21T00:00:00+00:00'

            def close(self):
                pass

        selected = [{'key': '12', 'title': 'Example S01E01 · Pilot', 'type': 'episode', 'imdb_id': 'tt123'}]
        progress.reset()
        imdb._start('Lese Auswahl')
        with patch.object(imdb, 'resolve_selected', return_value=selected), \
             patch('src.rating_overlay.imdb_cache.ImdbRatingCache', return_value=Cache()), \
             patch.object(overlay, 'run_overlay') as render:
            asyncio.run(imdb.run_selected('Shows', SimpleNamespace(rating_keys=['12'], mode='ratings')))
        render.assert_not_called()
        self.assertEqual(progress.extra['logs'][0]['rating'], 7.5)
        self.assertTrue(progress.extra['logs'][0]['changed'])


if __name__ == '__main__':
    unittest.main()
