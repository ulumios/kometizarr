import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from src.rating_overlay.api_cache import ApiCache
from src.rating_overlay.decision import Facts, Options, plan_item, plan_render
from src.rating_overlay.plex_poster_manager import PlexPosterManager
from src.services import config, overlay
from src.services.models import ProcessRequest
from src.services.progress import progress


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


class LostOverlayTest(unittest.TestCase):
    def test_lost_overlay_actions(self):
        facts = Facts(lost_overlay=True, has_overlay=True, has_original=True)
        adopt = plan_item(facts, Options())
        self.assertEqual((adopt.steps, adopt.origin), (['capture_current'], 'current'))
        self.assertTrue(plan_item(facts, Options(lost_overlay='restore')).force_render)
        self.assertEqual(plan_item(facts, Options(lost_overlay='report')).skip[1], 'Overlay verloren (nur gemeldet)')
        self.assertEqual(plan_render(Options(), True, 'a', 'a', False, force_render=True)[0], 'render')

    def test_detects_foreign_selected_poster(self):
        row = {'status': 'rendered', 'uploaded_thumb': '/thumb/1', 'uploaded_poster': 'upload://posters/abc'}
        ours = SimpleNamespace(ratingKey=1, thumb='/thumb/1', posters=Mock())
        self.assertFalse(overlay.overlay_lost('Movies', ours, row))
        ours.posters.assert_not_called()  # unchanged thumb needs no Plex request
        replaced = SimpleNamespace(ratingKey=1, thumb='/thumb/2', posters=lambda: [
            SimpleNamespace(ratingKey='upload://posters/abc', selected=False),
            SimpleNamespace(ratingKey='tmdb://poster', selected=True)])
        self.assertTrue(overlay.overlay_lost('Movies', replaced, row))
        refreshed = SimpleNamespace(ratingKey=1, thumb='/thumb/3', posters=lambda: [
            SimpleNamespace(ratingKey='upload://posters/abc', selected=True)])
        with patch.object(overlay, 'mark_item') as mark:
            self.assertFalse(overlay.overlay_lost('Movies', refreshed, row))
        mark.assert_called_once_with('Movies', refreshed, uploaded_thumb='/thumb/3')

    def test_items_without_known_upload_use_upload_marker(self):
        row = {'status': 'rendered', 'uploaded_thumb': '/thumb/1', 'uploaded_poster': None}
        item = SimpleNamespace(ratingKey=1, thumb='/thumb/2', posters=lambda: [
            SimpleNamespace(ratingKey='metadata://posters/agent', selected=True)])
        self.assertTrue(overlay.overlay_lost('Movies', item, row))


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
    manager.imdb_top250 = set()
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
            with patch.object(config, 'create_manager', return_value=manager), \
                 patch.object(config, 'load_settings', return_value={'imdb_direct': {}}), \
                 patch.object(overlay, 'item_row', return_value={'render_hash': 'same'}), \
                 patch.object(overlay, 'mark_item'), \
                 patch('src.rating_overlay.poster_storage.paths', return_value=(original, original)), \
                 patch('src.rating_overlay.kometa_conflicts.ManualPosterQueue') as queue, \
                 patch('src.rating_overlay.api_cache.ApiCache'):
                queue.return_value.state.return_value = 'none'
                progress.reset()
                asyncio.run(overlay.run_overlay(ProcessRequest(library_name='Movies', record_results=True)))
        manager.process_movie.assert_not_called()
        self.assertEqual(progress.results, {'1': 'unverändert'})


class KometaOriginalTest(unittest.TestCase):
    def test_finds_original_with_library_mapping_and_converts_png(self):
        from src.rating_overlay.kometa_originals import as_jpeg, find_original
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / 'overlays' / 'Movies Original Posters'
            store.mkdir(parents=True)
            Image.new('RGB', (4, 6), 'red').save(store / '42.png')
            settings = {'kometa': {'originals_dir': str(Path(folder) / 'overlays'),
                                   'library_map': {'Filme': 'Movies'}}}
            source = find_original(settings, 'Filme', 42)
            self.assertEqual(source, store / '42.png')
            self.assertIsNone(find_original(settings, 'Filme', 43))
            self.assertTrue(as_jpeg(source).startswith(b'\xff\xd8'))

    def test_adopting_kometa_original_replaces_backup(self):
        from src.rating_overlay.backup_manager import PosterBackupManager
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / 'overlays' / 'Movies Original Posters'
            store.mkdir(parents=True)
            Image.new('RGB', (4, 6), 'green').save(store / '7.jpg')
            backups = PosterBackupManager(Path(folder) / 'backups')
            manager = SimpleNamespace(library_name='Movies', backup_manager=backups)
            item = SimpleNamespace(type='movie', title='X', year=1, ratingKey=7, guids=[])
            with patch.object(config, 'load_settings', return_value={
                    'kometa': {'originals_dir': str(Path(folder) / 'overlays')}}):
                self.assertTrue(overlay.adopt_kometa_original(manager, item))
            self.assertTrue(backups.has_backup('Movies', item))


class ForceTakesOverKometaTest(unittest.TestCase):
    def test_force_resets_kometa_posters(self):
        labelled = plan_item(Facts(kometa_label=True), Options(force=True))
        self.assertEqual(labelled.steps, ['reset_agent'])
        with_original = plan_item(Facts(kometa_label=True, kometa_original=True), Options(force=True))
        self.assertEqual((with_original.steps, with_original.origin), (['use_kometa_original'], 'kometa'))

    def test_normal_run_still_protects_kometa_posters(self):
        self.assertEqual(plan_item(Facts(kometa_label=True), Options()).skip[1], 'Kometa-Konflikt: Reset erforderlich')

    def test_untagged_kometa_poster_is_detected_by_its_stored_original(self):
        facts = Facts(kometa_untagged=True, kometa_original=True)
        self.assertEqual(plan_item(facts, Options()).skip[1], 'Kometa-Konflikt: Reset erforderlich')
        self.assertEqual(plan_item(facts, Options(force=True)).steps, ['use_kometa_original'])
        self.assertEqual(plan_item(facts, Options(operation='imdb_overlay')).skip[1], 'Kometa-Konflikt: übersprungen')
        # once Kometizarr rendered the item, a leftover Kometa original no longer matters
        self.assertEqual(plan_item(Facts(kometa_untagged=True, has_overlay=True, has_original=True), Options()).steps, [])


if __name__ == '__main__':
    unittest.main()
