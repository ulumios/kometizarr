import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services import config, maintenance


def guid(value):
    return SimpleNamespace(id=value)


def make(folder, *parts, files=('original.jpg',), metadata=None):
    path = Path(folder, *parts)
    path.mkdir(parents=True, exist_ok=True)
    for name in files:
        (path / name).write_bytes(b'x' * 10)
    if metadata is not None:
        (path / 'metadata.json').write_text(json.dumps(metadata))
    return path


class BackupAuditTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.patch = patch.object(config, 'BACKUP_DIR', Path(self.folder))
        self.patch.start()
        self.show = SimpleNamespace(type='show', ratingKey=10, guids=[guid('imdb://tt10')])
        self.episode = SimpleNamespace(type='episode', ratingKey=11, grandparentRatingKey=10, parentIndex=1, index=1, guids=[])
        self.movie = SimpleNamespace(type='movie', ratingKey=20, guids=[guid('imdb://tt20')])

    def tearDown(self):
        self.patch.stop()

    def test_overview_counts_sizes(self):
        make(self.folder, 'Movies', 'tt20', files=('original.jpg', 'overlay.jpg'))
        entry = maintenance.overview()['libraries'][0]
        self.assertEqual((entry['library'], entry['originals'], entry['overlays'], entry['bytes']), ('Movies', 1, 1, 20))

    def test_finds_orphans_and_legacy_folders(self):
        make(self.folder, 'Shows', 'tt10', 'S01E01')
        make(self.folder, 'Shows', 'tt10', 'S09E09')          # episode no longer in Plex
        make(self.folder, 'Shows', 'tt99')                    # show no longer in Plex
        make(self.folder, 'Shows', 'tt77', metadata={'rating_key': 10})  # ID changed, item still exists
        make(self.folder, 'Shows', 'Old Title (2001)', files=('poster_original.jpg',))
        report = maintenance.audit_library('Shows', [self.show, self.episode])
        self.assertEqual(sorted(o['path'] for o in report['orphans']), ['tt10/S09E09', 'tt99'])
        self.assertEqual([entry['path'] for entry in report['legacy']], ['Old Title (2001)'])

    def test_refuses_implausible_audit(self):
        for number in range(30):
            make(self.folder, 'Movies', f'tt{number}')
        with self.assertRaises(ValueError):
            maintenance.audit_library('Movies', [SimpleNamespace(type='movie', ratingKey=1, guids=[])])

    def test_deletes_only_confirmed_orphans(self):
        keep = make(self.folder, 'Movies', 'tt20')
        orphan = make(self.folder, 'Movies', 'tt21')
        with patch.object(config, 'plex_server') as plex:
            plex.return_value.library.section.return_value = SimpleNamespace(
                type='movie', all=lambda **_kw: [self.movie])
            result = maintenance.delete_orphans('Movies', ['tt21', 'tt20', '../../etc'])
        self.assertEqual(result['deleted'], ['tt21'])
        self.assertTrue(keep.exists())
        self.assertFalse(orphan.exists())


class PlexUploadsTest(unittest.TestCase):
    def test_lists_only_unselected_uploads_that_plex_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            item = SimpleNamespace(type='movie', guid='plex://movie/abc', posters=lambda: [
                SimpleNamespace(ratingKey='upload://posters/old', selected=False),
                SimpleNamespace(ratingKey='upload://posters/current', selected=True),
                SimpleNamespace(ratingKey='tmdb://poster', selected=False)])
            uploads = maintenance.bundle_dir(base, item) / 'Uploads' / 'posters'
            uploads.mkdir(parents=True)
            for name in ('old', 'current', 'unknown'):
                (uploads / name).write_bytes(b'x')
            self.assertEqual(maintenance.stale_uploads(base, item), [uploads / 'old'])
            self.assertTrue(str(maintenance.bundle_dir(base, item)).endswith('.bundle'))


if __name__ == '__main__':
    unittest.main()
