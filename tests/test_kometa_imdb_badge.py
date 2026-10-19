import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.rating_overlay.imdb_top250 import top250_ids
from src.rating_overlay.multi_rating_badge import MultiRatingBadge
from src.rating_overlay.plex_poster_manager import PlexPosterManager


class KometaBadgeTest(unittest.TestCase):
    badges = MultiRatingBadge()

    def test_geometry_matches_kometa_defaults(self):
        badge = self.badges.create_individual_badge('imdb', 8.4, (1000, 1500), {})
        # 160x160 box + 15 padding on each side, rectangle includes its end pixel
        self.assertEqual(badge.size, (191, 191))
        self.assertEqual(badge.getpixel((95, 3))[3], 0x99)          # #00000099 background
        self.assertEqual(badge.getpixel((0, 0))[3], 0)              # rounded corner (radius 30)
        logo = self.badges.kometa_images['IMDb']
        # logo 149x75 on top: box is centered, logo wider than "8.4" text
        self.assertEqual(badge.getpixel((15 + 5 + 74, 15 + 5 + 40))[:3], logo.getpixel((74, 40))[:3])

    def test_top250_uses_kometa_top_image(self):
        normal = self.badges.create_individual_badge('imdb', 9.0, (1000, 1500), {})
        top = self.badges.create_individual_badge('imdb', 9.0, (1000, 1500), {'imdb_top250': True})
        self.assertNotEqual(normal.tobytes(), top.tobytes())

    def test_scale_and_episode_canvas(self):
        self.assertEqual(self.badges.create_individual_badge('imdb', 7, (1000, 1500), {'imdb_scale': 50}).size, (97, 97))
        # Kometa uses the same pixel sizes on the 1920x1080 episode canvas
        self.assertEqual(self.badges.create_individual_badge('imdb', 7, (1920, 1080), {}).size, (191, 191))

    def test_compact_variant_is_still_available(self):
        compact = self.badges.create_individual_badge('imdb', 7, (1000, 1500), {'imdb_variant': 'compact'})
        self.assertEqual(compact.size, (90, 94))


class Top250InputsTest(unittest.TestCase):
    def manager(self, top):
        manager = PlexPosterManager.__new__(PlexPosterManager)
        manager.rating_sources, manager.badge_style, manager.media_overlay = {}, {}, {}
        manager.imdb_ratings, manager.imdb_top250 = {}, top
        manager.library = SimpleNamespace(type='movie')
        manager.rating_fetcher = Mock(**{'fetch_mdblist_rating.return_value': None})
        manager._extract_plex_ratings = lambda _item: {'imdb': 9.3}
        return manager

    def test_top250_membership_changes_style_and_hash(self):
        item = SimpleNamespace(type='movie', title='X', guids=[SimpleNamespace(id='imdb://tt0111161')], media=[])
        inside = self.manager({'tt0111161'}).collect_inputs(item)
        outside = self.manager(set()).collect_inputs(item)
        self.assertTrue(inside['style']['imdb_top250'])
        self.assertFalse(outside['style']['imdb_top250'])
        self.assertNotEqual(PlexPosterManager.render_hash(inside), PlexPosterManager.render_hash(outside))


class Top250FetchTest(unittest.TestCase):
    def test_cached_for_a_day_and_falls_back_to_last_list(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'cache.db'
            calls = []

            def fetch(chart):
                calls.append(chart)
                return [f'tt{chart}{n}' for n in range(250)]
            ids = top250_ids(db, fetch)
            self.assertEqual(len(ids), 500)
            self.assertEqual(top250_ids(db, fetch), ids)
            self.assertEqual(len(calls), 2)  # second call served from the cache

            import sqlite3
            con = sqlite3.connect(db)
            con.execute("UPDATE api_cache SET fetched_at=0 WHERE key='imdb-top250'")
            con.commit(); con.close()

            def offline(_chart):
                raise ConnectionError('offline')
            self.assertEqual(top250_ids(db, offline), ids)
            self.assertEqual(top250_ids(Path(folder) / 'empty.db', offline), set())

    def test_rejects_truncated_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(top250_ids(Path(folder) / 'c.db', lambda _chart: ['tt1']), set())


if __name__ == '__main__':
    unittest.main()
