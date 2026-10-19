import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.rating_overlay.kometa_conflicts import KOMETA_LABEL, remove_overlay_label
from src.services import config, restore, tasks
from src.services.models import FreshPostersRequest, ProcessRequest
from src.services.progress import progress
from web.backend.routes import settings as settings_routes


class UnifiedWorkflowTest(unittest.TestCase):
    def test_saved_overlay_options_fill_only_missing_values(self):
        settings = {'badge_style': {'font': 'saved'}, 'badge_positions': {'imdb': {'x': 1, 'y': 1}},
                    'rating_sources': {'imdb': True}, 'media_overlay': {'source': True}}
        request = ProcessRequest(library_name='Movies', rating_sources={'tmdb': True})
        config.apply_saved_overlay_options(request, settings)
        self.assertEqual(request.rating_sources, {'tmdb': True})
        self.assertEqual(request.badge_style, {'font': 'saved'})
        self.assertEqual(request.media_overlay, {'source': True})

    def test_legacy_unified_badge_keeps_its_position(self):
        request = ProcessRequest(library_name='Movies', badge_position={'x': 5, 'y': 5})
        config.apply_saved_overlay_options(request, {'badge_positions': {'imdb': {'x': 1, 'y': 1}}})
        self.assertIsNone(request.badge_positions)

    def test_library_profile_overrides_global_design(self):
        settings = {'badge_style': {'font': 'global'}, 'rating_sources': {'imdb': True},
                    'library_profiles': {'Anime': {'badge_style': {'font': 'anime'}}}}
        anime = config.apply_saved_overlay_options(ProcessRequest(library_name='Anime'), settings)
        movies = config.apply_saved_overlay_options(ProcessRequest(library_name='Movies'), settings)
        self.assertEqual(anime.badge_style, {'font': 'anime'})
        self.assertEqual(anime.rating_sources, {'imdb': True})  # not in profile: global
        self.assertEqual(movies.badge_style, {'font': 'global'})

    def test_backup_folder_cannot_escape_backup_root(self):
        self.assertEqual(config.backup_library_dir('Movies').name, 'Movies')
        for name in ('..', '../etc', 'Movies/../..', ''):
            with self.assertRaises(ValueError):
                config.backup_library_dir(name)

    def test_delete_backups_rejects_traversal(self):
        with patch.object(settings_routes.shutil, 'rmtree') as rmtree:
            result = asyncio.run(settings_routes.delete_backups('..', confirm='DELETE'))
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
        with patch.object(tasks, 'enqueue', new_callable=AsyncMock, return_value=7) as enqueue:
            result = asyncio.run(settings_routes.start_fetch_fresh_posters(
                FreshPostersRequest(library_name='Movies')))
        kind, payload = enqueue.call_args.args
        self.assertEqual((kind, payload['library_name'], payload['reset_to_plex']),
                         ('fresh_posters', 'Movies', True))
        self.assertEqual(result['task_id'], 7)
        settings_routes._fresh_poster_tasks.pop(7, None)

    def test_restore_clears_error_from_previous_run(self):
        progress.reset()
        progress.error = 'old failure'
        library = SimpleNamespace(all=lambda: [], type='movie')
        server = SimpleNamespace(library=SimpleNamespace(section=lambda _: library))
        with patch.object(config, 'plex_server', return_value=server):
            asyncio.run(restore.run_restore(ProcessRequest(library_name='Movies')))
        self.assertIsNone(progress.error)

if __name__ == '__main__':
    unittest.main()
