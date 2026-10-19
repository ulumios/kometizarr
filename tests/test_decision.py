import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from src.rating_overlay.api_cache import ApiCache
from src.rating_overlay.decision import Facts, Options, plan_item, plan_render
from src.rating_overlay.plex_poster_manager import PlexPosterManager
from web.backend import main


class PlanItemTest(unittest.TestCase):
    def test_unprocessed_kometa_item_needs_reset(self):
        plan = plan_item(Facts(kometa_label=True), Options())
        self.assertEqual(plan.skip, ('skipped', 'Kometa-Konflikt: Reset erforderlich'))
        self.assertTrue(plan.remember_conflict)

    def test_auto_reset_prefers_kometa_original(self):
        self.assertEqual(plan_item(Facts(kometa_label=True), Options(auto_reset_kometa=True)).steps,
                         ['reset_agent'])
        plan = plan_item(Facts(kometa_label=True, kometa_original=True), Options(auto_reset_kometa=True))
        self.assertEqual((plan.steps, plan.origin), (['use_kometa_original'], 'kometa'))

    def test_manual_poster_change_captures_before_render(self):
        self.assertEqual(plan_item(Facts(manual_state='waiting'), Options()).skip[1],
                         'wartet auf manuelles Plex-Poster')
        self.assertEqual(plan_item(Facts(manual_state='changed'), Options()).steps, ['capture_manual'])

    def test_imdb_overlay_never_uses_kometa_poster_as_original(self):
        plan = plan_item(Facts(origin='current_with_label', has_original=True), Options(operation='imdb_overlay'))
        self.assertEqual(plan.skip[1], 'Unsicheres Original: Kometa-Poster')
        self.assertEqual(plan_item(Facts(), Options(operation='imdb_overlay')).steps, ['capture_if_missing'])


class PlanRenderTest(unittest.TestCase):
    def test_render_only_when_something_changed(self):
        options = Options()
        self.assertEqual(plan_render(options, True, 'a', 'a', False), ('skip', 'unverändert'))
        self.assertEqual(plan_render(options, True, 'a', 'b', False)[0], 'render')
        self.assertEqual(plan_render(options, False, 'a', 'a', False)[0], 'render')
        self.assertEqual(plan_render(options, True, None, 'a', False)[0], 'baseline')
        self.assertEqual(plan_render(Options(force=True), True, 'a', 'a', False)[0], 'render')
        self.assertEqual(plan_render(options, True, 'a', 'a', True)[0], 'render')


def manager_stub(ratings, media=None):
    manager = PlexPosterManager.__new__(PlexPosterManager)
    manager.rating_sources, manager.badge_style, manager.media_overlay = {}, {'size': 1}, media or {}
    manager.imdb_ratings = {}
    manager.library = SimpleNamespace(type='movie')
    manager.rating_fetcher = Mock(**{'fetch_tmdb_rating.return_value': None,
                                     'fetch_omdb_rating.return_value': None,
                                     'fetch_mdblist_rating.return_value': None})
    manager._extract_plex_ratings = lambda _item: dict(ratings)
    return manager


class InputsTest(unittest.TestCase):
    item = SimpleNamespace(type='movie', title='X', guids=[SimpleNamespace(id='imdb://tt1')], media=[])

    def test_hash_changes_with_rating_style_and_original(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'original.jpg'
            Image.new('RGB', (4, 6), 'red').save(original)
            base = manager_stub({'imdb': 7.1}).collect_inputs(self.item)
            same = manager_stub({'imdb': 7.1}).collect_inputs(self.item)
            changed = manager_stub({'imdb': 7.2}).collect_inputs(self.item)
            h = PlexPosterManager.render_hash
            self.assertEqual(h(base, original), h(same, original))
            self.assertNotEqual(h(base, original), h(changed, original))
            self.assertNotEqual(h(base, original), h({**base, 'style': {'size': 2}}, original))
            Image.new('RGB', (4, 6), 'blue').save(original)
            self.assertNotEqual(h(base), h(base, original))

    def test_missing_ratings_is_a_problem(self):
        inputs = manager_stub({}).collect_inputs(self.item)
        self.assertEqual(inputs['problem'], ('failed', 'Keine Wertungen verfügbar'))

    def test_api_answers_are_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = ApiCache(Path(folder) / 'cache.db')
            calls = []
            fetch = lambda: calls.append(1) or {'imdb_rating': '7.0'}
            self.assertEqual(cache.get_or_fetch('omdb:tt1', fetch), {'imdb_rating': '7.0'})
            self.assertEqual(cache.get_or_fetch('omdb:tt1', fetch), {'imdb_rating': '7.0'})
            self.assertEqual(len(calls), 1)
            cache.close()


class RunSkipsUnchangedTest(unittest.TestCase):
    def test_unchanged_item_is_not_uploaded_again(self):
        item = SimpleNamespace(type='movie', title='X', ratingKey=1, year=2000, labels=[], guids=[])
        manager = Mock(library=SimpleNamespace(all=lambda: [item], type='movie'), library_name='Movies')
        manager.collect_inputs.return_value = {'problem': None, 'ratings': {'imdb': 7}}
        manager.render_hash.return_value = 'same'
        manager.backup_manager.has_overlay.return_value = True
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'original.jpg'
            with patch.object(main, '_create_manager', return_value=manager), \
                 patch.object(main, '_load_settings', return_value={'imdb_direct': {}}), \
                 patch.object(main, '_item_row', return_value={'render_hash': 'same'}), \
                 patch.object(main, '_known_poster_origin', return_value=None), \
                 patch.object(main, '_mark_item'), \
                 patch('src.rating_overlay.poster_storage.paths', return_value=(original, original)), \
                 patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
                 patch('src.rating_overlay.api_cache.ApiCache'), \
                 patch.object(main, 'broadcast_progress', new_callable=AsyncMock):
                queue.return_value.state.return_value = 'none'
                main.processing_state['stop_requested'] = False
                asyncio.run(main.process_library_background(main.ProcessRequest(
                    library_name='Movies', record_results=True)))
        manager.process_movie.assert_not_called()
        self.assertEqual(main.processing_state['item_results'], {'1': 'unverändert'})


if __name__ == '__main__':
    unittest.main()
