import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.rating_overlay.kometa_conflicts import KOMETA_LABEL, remove_overlay_label
from web.backend import main


class UnifiedWorkflowTest(unittest.TestCase):
    def test_saved_overlay_options_fill_only_missing_values(self):
        settings = {'badge_style': {'font': 'saved'}, 'badge_positions': {'imdb': {'x': 1, 'y': 1}},
                    'rating_sources': {'imdb': True}, 'media_overlay': {'source': True}}
        request = main.ProcessRequest(library_name='Movies', rating_sources={'tmdb': True})
        main._apply_saved_overlay_options(request, settings)
        self.assertEqual(request.rating_sources, {'tmdb': True})
        self.assertEqual(request.badge_style, {'font': 'saved'})
        self.assertEqual(request.media_overlay, {'source': True})

    def test_legacy_unified_badge_keeps_its_position(self):
        request = main.ProcessRequest(library_name='Movies', badge_position={'x': 5, 'y': 5})
        main._apply_saved_overlay_options(request, {'badge_positions': {'imdb': {'x': 1, 'y': 1}}})
        self.assertIsNone(request.badge_positions)

    def test_backup_folder_cannot_escape_backup_root(self):
        self.assertEqual(main._backup_library_dir('Movies').name, 'Movies')
        for name in ('..', '../etc', 'Movies/../..', ''):
            with self.assertRaises(ValueError):
                main._backup_library_dir(name)

    def test_delete_backups_rejects_traversal(self):
        with patch.object(main.shutil, 'rmtree') as rmtree:
            result = asyncio.run(main.delete_backups('..', confirm='DELETE'))
        self.assertIn('error', result)
        rmtree.assert_not_called()

    def test_remove_overlay_label_only_touches_kometa_items(self):
        plain = SimpleNamespace(labels=[], removeLabel=Mock())
        self.assertFalse(remove_overlay_label(plain))
        plain.removeLabel.assert_not_called()
        kometa = SimpleNamespace(labels=[SimpleNamespace(tag=KOMETA_LABEL)], removeLabel=Mock())
        self.assertTrue(remove_overlay_label(kometa))
        kometa.removeLabel.assert_called_once_with(KOMETA_LABEL)

    def test_fresh_posters_uses_queued_agent_reset(self):
        with patch.object(main, '_enqueue_task', new_callable=AsyncMock, return_value=7) as enqueue:
            result = asyncio.run(main.start_fetch_fresh_posters(
                main.FreshPostersRequest(library_name='Movies')))
        kind, payload = enqueue.call_args.args
        self.assertEqual((kind, payload['library_name'], payload['reset_to_plex']),
                         ('fresh_posters', 'Movies', True))
        self.assertEqual(result['task_id'], 7)
        main._fresh_poster_tasks.pop(7, None)

    def test_restore_clears_error_from_previous_run(self):
        main.restore_state['error'] = 'old failure'
        library = SimpleNamespace(all=lambda: [], type='movie')
        server = SimpleNamespace(library=SimpleNamespace(section=lambda _: library))
        with patch.object(main, '_plex_server', return_value=server), \
             patch.object(main, 'broadcast_restore_progress', new_callable=AsyncMock):
            main.restore_state['stop_requested'] = False
            asyncio.run(main.restore_library_background(main.ProcessRequest(library_name='Movies')))
        self.assertNotIn('error', main.restore_state)


if __name__ == '__main__':
    unittest.main()
