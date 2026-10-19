import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.rating_overlay import kometa_style as ks
from src.rating_overlay.imdb_top250 import rt_top_ids
from src.rating_overlay.media_badges import draw_media_badges


class KometaImagesTest(unittest.TestCase):
    def test_rt_image_follows_kometa_levels(self):
        self.assertEqual(ks.rating_image_name('rt_critic', 59.0), 'RT-Crit-Rotten')
        self.assertEqual(ks.rating_image_name('rt_critic', 60.0), 'RT-Crit-Direct')
        self.assertEqual(ks.rating_image_name('rt_critic', 95.0, top=True), 'RT-Crit-Top')
        self.assertEqual(ks.rating_image_name('rt_audience', 88.0, top=True), 'RT-Aud-Top')
        self.assertEqual(ks.rating_image_name('tmdb', 7.0, top=True), 'TMDb')  # Kometa has no TMDB top
        for name in ('IMDb', 'IMDbTop', 'TMDb', 'RT-Crit-Direct', 'RT-Aud-Rotten', 'flags/de', 'flags/us'):
            self.assertIsNotNone(ks.image(name), name)

    def test_text_uses_kometa_formatting(self):
        self.assertEqual(ks.rating_text('imdb', 8), '8.0')
        self.assertEqual(ks.rating_text('tmdb', 7.46), '74%')   # truncated like int(value * 10)
        self.assertEqual(ks.rating_text('rt_audience', 92.0), '92%')

    def test_text_box_is_kometa_size_and_grows_for_long_labels(self):
        self.assertEqual(ks.text_badge('BluRay', (1000, 1500)).size, (306, 106))
        self.assertGreater(ks.text_badge('Abgeschlossen', (1000, 1500), status=True).width, 306)

    def test_language_rows(self):
        rows, spacing = ks.language_rows(['DE', 'EN'], (1920, 1080))
        self.assertEqual((len(rows), rows[0].width, spacing), (2, 191, 61))


class KometaMediaBadgesTest(unittest.TestCase):
    def test_draws_kometa_boxes_at_configured_corner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'e.jpg'
            Image.new('RGB', (1920, 1080), (200, 200, 200)).save(path)
            draw_media_badges(str(path), 'BluRay', [('DE', ''), ('EN', '')],
                              {'episode': True, 'source_position': {'x': 30, 'y': 30},
                               'languages_position': {'x': 30, 'y': 30}}, badge_style={'variant': 'kometa'})
            with Image.open(path) as result:
                self.assertLess(sum(result.getpixel((30 + 150, 1080 - 30 - 10))), 400)   # dark source box
                self.assertLess(sum(result.getpixel((1920 - 30 - 191 + 106, 1080 - 30 - 30))), 400)  # language box, between flag and text
                self.assertGreater(sum(result.getpixel((960, 540))), 590)                # rest untouched


class RtTopTest(unittest.TestCase):
    def test_lists_are_mapped_per_rating_source(self):
        with tempfile.TemporaryDirectory() as folder:
            fetched = lambda name: [f'tt{name}{n}' for n in range(10)]
            tops = rt_top_ids(Path(folder) / 'c.db', fetched)
            self.assertIn('ttcertifiedfreshmovies1', tops['rt_critic'])
            self.assertIn('ttverifiedhotshows9', tops['rt_audience'])
            self.assertNotIn('ttverifiedhotshows9', tops['rt_critic'])


class AssetsInRepositoryTest(unittest.TestCase):
    """Images must be committed, not only present on disk (a .gitignore rule once hid them)."""

    def test_kometa_assets_are_tracked_by_git(self):
        import subprocess
        root = Path(__file__).resolve().parent.parent
        try:
            tracked = set(subprocess.run(['git', 'ls-files', 'assets'], cwd=root, capture_output=True,
                                         text=True, check=True).stdout.split())
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('not a git checkout')
        needed = [f'assets/logos/kometa/{name}.png' for name in (
            'IMDb', 'IMDbTop', 'TMDb', 'RT-Crit-Direct', 'RT-Crit-Rotten', 'RT-Crit-Top',
            'RT-Aud-Direct', 'RT-Aud-Rotten', 'RT-Aud-Top')]
        needed += [f'assets/logos/kometa/flags/{code}.png' for code in ('de', 'us', 'gb', 'fr', 'es', 'it', 'jp')]
        needed += ['assets/fonts/Inter-Bold.ttf', 'assets/fonts/Inter-Medium.ttf']
        self.assertEqual([path for path in needed if path not in tracked], [])


if __name__ == '__main__':
    unittest.main()
