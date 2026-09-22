import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.rating_overlay.kometa_conflicts import ManualPosterQueue, has_overlay_label, select_agent_poster
from web.backend import main


class KometaTransitionTest(unittest.TestCase):
    def test_manual_label_removal_blocks_until_poster_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            selected = SimpleNamespace(selected=True, ratingKey='upload://kometa')
            item = SimpleNamespace(ratingKey=123, thumb='/thumb/first', posters=lambda: [selected])
            queue = ManualPosterQueue(Path(folder) / 'pending.json')
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
        with patch.object(main, 'PlexPosterManager', return_value=manager), \
             patch.object(main, '_load_settings', return_value={'media_overlay': {},
                                                                'imdb_direct': {'enabled': False},
                                                                'kometa_conflicts': {'auto_reset': False}}), \
             patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
             patch.object(main, 'broadcast_progress', new_callable=AsyncMock):
            queue.return_value.state.return_value = 'none'
            main.processing_state['stop_requested'] = False
            asyncio.run(main.process_library_background(main.ProcessRequest(library_name='Movies')))
        manager.process_movie.assert_not_called()
        self.assertEqual(main.processing_state['skipped'], 1)
        self.assertEqual(main.processing_state['failed'], 0)

    def test_library_search_filters_cached_entries(self):
        cache_key = ('Shows', '')
        old = main._browse_entries_cache.get(cache_key)
        try:
            main._browse_entries_cache[cache_key] = (float('inf'), [
                {'title': 'Pilot', 'type': 'episode', 'series': 'Lost', 'year': 2004},
                {'title': 'Finale', 'type': 'episode', 'series': 'Another', 'year': 2005},
            ])
            result = asyncio.run(main.browse_library('Shows', q='lost'))
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['title'], 'Pilot')
        finally:
            if old is None:
                main._browse_entries_cache.pop(cache_key, None)
            else:
                main._browse_entries_cache[cache_key] = old

    def test_cache_only_imdb_run_does_not_render(self):
        class Cache:
            def ratings(self, _ids):
                return {}

            def refresh(self, _ids):
                return {'tt123': 8.4}

            def updated_at(self):
                return '2026-09-22T00:00:00+00:00'

            def applied(self, *_args):
                return None

            def close(self):
                pass

        server = SimpleNamespace(library=SimpleNamespace(sections=lambda: [SimpleNamespace(title='Movies')]))
        with patch.object(main, '_load_settings', return_value={'imdb_direct': {'libraries': ['Movies']}}), \
             patch('plexapi.server.PlexServer', return_value=server), \
             patch.object(main, '_collect_imdb_items', return_value={'Movies': [('1', 'tt123')]}), \
             patch('src.rating_overlay.imdb_cache.ImdbRatingCache', return_value=Cache()), \
             patch.object(main, 'process_library_background', new_callable=AsyncMock) as render:
            asyncio.run(main._run_imdb_sync('ratings'))
            render.assert_not_called()
        self.assertEqual(main.imdb_sync_state['pending'], 1)
        self.assertEqual(main.imdb_sync_state['rendered'], 0)

    def test_conflict_scan_uses_cached_response(self):
        old = main._conflict_scans.get('Shows')
        try:
            main._conflict_scans['Shows'] = {
                'is_running': False, 'items': [{'key': '7'}],
                'error': None, 'updated_at': main.time.monotonic()}
            with patch.object(main, '_scan_kometa_conflicts') as scan:
                result = asyncio.run(main.get_kometa_conflicts('Shows'))
                self.assertEqual(result['items'], [{'key': '7'}])
                self.assertFalse(result['is_running'])
                scan.assert_not_called()
        finally:
            if old is None:
                main._conflict_scans.pop('Shows', None)
            else:
                main._conflict_scans['Shows'] = old


if __name__ == '__main__':
    unittest.main()
