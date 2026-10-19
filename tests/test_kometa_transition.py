import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.rating_overlay.kometa_conflicts import ManualPosterQueue, has_overlay_label, select_agent_poster
import time

from src.services import config, conflicts, imdb, overlay
from src.services.models import ProcessRequest
from src.services.progress import progress


class KometaTransitionTest(unittest.TestCase):
    def test_manual_label_removal_blocks_until_poster_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            selected = SimpleNamespace(selected=True, ratingKey='upload://kometa')
            item = SimpleNamespace(ratingKey=123, thumb='/thumb/first', posters=lambda: [selected])
            queue = ManualPosterQueue(Path(folder) / 'state.sqlite3')
            queue.mark('Series', item)
            self.assertTrue(queue.is_pending('Series', item))
            selected.ratingKey = 'agent://new'
            item.thumb = '/thumb/second'
            self.assertFalse(queue.is_pending('Series', item))
            self.assertEqual(queue.state('Series', item), 'changed')

    def test_agent_reset_never_selects_uploaded_poster(self):
        uploaded = SimpleNamespace(ratingKey='upload://kometa', select=Mock())
        agent = SimpleNamespace(ratingKey='agent://tmdb', select=Mock())
        item = SimpleNamespace(posters=lambda: [uploaded, agent], reload=Mock())
        self.assertTrue(select_agent_poster(item))
        uploaded.select.assert_not_called()
        agent.select.assert_called_once()
        item.reload.assert_called_once()

    def test_unprocessed_overlay_label_is_skipped_before_backup(self):
        item = SimpleNamespace(type='movie', title='Example', ratingKey=123, year=2020,
                               labels=[SimpleNamespace(tag='Overlay')], guids=[])
        library = SimpleNamespace(all=lambda: [item], type='movie')
        manager = Mock(library=library, library_name='Movies', backup_manager=Mock())
        manager.backup_manager.has_overlay.return_value = False
        with patch.object(config, 'create_manager', return_value=manager), \
             patch.object(config, 'load_settings', return_value={'media_overlay': {},
                                                                'imdb_direct': {'enabled': False},
                                                                'kometa_conflicts': {'auto_reset': False}}), \
             patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
             patch('src.rating_overlay.api_cache.ApiCache'):
            queue.return_value.state.return_value = 'none'
            progress.reset()
            asyncio.run(overlay.run_overlay(ProcessRequest(library_name='Movies')))
        manager.process_movie.assert_not_called()
        self.assertEqual(progress.skipped, 1)
        self.assertEqual(progress.failed, 0)

    def test_library_search_filters_cached_entries(self):
        from src.rating_overlay.media_index import MediaIndex
        with tempfile.TemporaryDirectory() as folder:
            index = MediaIndex(Path(folder) / 'index.sqlite3')
            entries = [SimpleNamespace(ratingKey=1, title='Lost', type='show', year=2004,
                                       index=None, parentRatingKey=None),
                       SimpleNamespace(ratingKey=2, title='Pilot', type='episode', year=2004,
                                       index=1, parentRatingKey=3, parentIndex=1, grandparentTitle='Lost'),
                       SimpleNamespace(ratingKey=3, title='Staffel 1', type='season', year=None,
                                       index=1, parentRatingKey=1)]
            index.replace_library('Shows', entries)
            result = index.browse('Shows', episodes=True, q='lost')
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['title'], 'Pilot')
            self.assertEqual(index.browse('Shows', parent_key=1)['items'][0]['type'], 'season')
            index.close()

    def test_index_skips_deleted_plex_item(self):
        from plexapi.exceptions import NotFound
        from src.rating_overlay.media_index import MediaIndex

        class Deleted:
            ratingKey = 180524

            @property
            def title(self):
                raise NotFound('(404) not_found')

        with tempfile.TemporaryDirectory() as folder:
            index = MediaIndex(Path(folder) / 'index.sqlite3')
            index.replace_library('Shows', [Deleted(), SimpleNamespace(
                ratingKey=42, title='Alive', type='show')])
            self.assertEqual(index.browse('Shows')['total'], 1)
            index.close()

    def test_cache_only_imdb_run_does_not_render(self):
        class Cache:
            def ratings(self, _ids):
                return {}

            def refresh(self, _ids, _progress=None):
                return {'tt123': 8.4}

            def updated_at(self):
                return '2026-09-22T00:00:00+00:00'

            def applied(self, *_args):
                return None

            def close(self):
                pass

        server = SimpleNamespace(library=SimpleNamespace(sections=lambda: [SimpleNamespace(title='Movies')]))
        with patch.object(config, 'load_settings', return_value={'imdb_direct': {'libraries': ['Movies']}}), \
             patch('plexapi.server.PlexServer', return_value=server), \
             patch.object(imdb, 'collect_items', return_value={'Movies': [('1', 'tt123')]}), \
             patch('src.rating_overlay.imdb_cache.ImdbRatingCache', return_value=Cache()), \
             patch.object(overlay, 'run_overlay', new_callable=AsyncMock) as render:
            progress.reset()
            imdb._start('Lese Plex')
            asyncio.run(imdb.run_sync('ratings'))
            render.assert_not_called()
        self.assertEqual(progress.extra['pending'], 1)
        self.assertEqual(progress.extra['rendered'], 0)

    def test_conflict_scan_uses_cached_response(self):
        old = conflicts.snapshots.get('Shows')
        try:
            conflicts.snapshots['Shows'] = {
                'is_running': False, 'items': [{'key': '7'}],
                'error': None, 'updated_at': time.time()}
            with patch.object(conflicts, 'scan_library') as scan:
                result = asyncio.run(conflicts.get_conflicts('Shows'))
                self.assertEqual(result['items'], [{'key': '7'}])
                self.assertFalse(result['is_running'])
                scan.assert_not_called()
        finally:
            if old is None:
                conflicts.snapshots.pop('Shows', None)
            else:
                conflicts.snapshots['Shows'] = old

    def test_conflict_scan_skips_deleted_plex_episode(self):
        from plexapi.exceptions import NotFound
        from src.rating_overlay.media_index import MediaIndex

        class Deleted:
            ratingKey = 180524

            @property
            def labels(self):
                raise NotFound('(404) not_found')

        valid = SimpleNamespace(ratingKey=42, title='Pilot', type='episode',
                                labels=[SimpleNamespace(tag='Overlay')], grandparentTitle='Show',
                                parentIndex=1, index=1)
        library = SimpleNamespace(type='show', search=lambda libtype, label: [Deleted(), valid]
                                  if libtype == 'episode' else [], fetchItem=Mock())
        server = SimpleNamespace(library=SimpleNamespace(section=lambda _: library))
        with tempfile.TemporaryDirectory() as folder, \
             patch('plexapi.server.PlexServer', return_value=server), \
             patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
             patch('src.rating_overlay.media_index.MediaIndex', side_effect=lambda: MediaIndex(Path(folder) / 'index.sqlite3')), \
             patch('src.rating_overlay.backup_manager.PosterBackupManager') as backups:
            queue.return_value.keys.return_value = []
            queue.return_value.state.return_value = 'none'
            backups.return_value.backup_dir = Path(folder)
            scan_progress = {'skipped': 0}
            result = conflicts.scan_library('Shows', scan_progress)
        self.assertEqual([entry['key'] for entry in result], ['42'])
        self.assertEqual(scan_progress['skipped'], 1)
        self.assertEqual(scan_progress['processed'], 1)


if __name__ == '__main__':
    unittest.main()
