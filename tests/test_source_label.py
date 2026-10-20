import unittest
from types import SimpleNamespace

from src.rating_overlay.media_badges import source_label


def item(*files):
    return SimpleNamespace(media=[SimpleNamespace(parts=[SimpleNamespace(file=f) for f in files])])


class SourceLabelTest(unittest.TestCase):
    def test_bluray_in_radarr_and_sonarr_names(self):
        for name in ['Film (2020) Bluray-720p.mkv', 'Film (2020) [Bluray-720p].mkv',
                     'Film (2020) {imdb-tt1} [Bluray-1080p][AC3 5.1][x264]-GRP.mkv',
                     'Film.2020.1080p.BluRay.x264-GRP.mkv', 'Film (2020) (Blu-ray 1080p).mkv',
                     'Film (2020) [Remux-2160p].mkv', 'Show - S01E02 - Titel [Bluray-1080p].mkv']:
            self.assertEqual(source_label(item('/media/x/' + name)), 'BluRay', name)

    def test_prerelease_and_plain_files(self):
        self.assertEqual(source_label(item('/m/Film (2024) [CAM].mkv')), 'PreRelease')
        self.assertIsNone(source_label(item('/m/Film (2020) [WEBDL-1080p].mkv')))
        self.assertIsNone(source_label(item('/m/Bluraylike Film (2020).mkv')))
        self.assertIsNone(source_label(SimpleNamespace(media=[])))

    def test_folder_name_when_file_name_says_nothing(self):
        self.assertEqual(source_label(item('/m/Film (2020) [Bluray-720p]/film.mkv')), 'BluRay')
        # The file name wins over the folder
        self.assertEqual(source_label(item('/m/Film BluRay/Film [CAM].mkv')), 'PreRelease')

    def test_custom_label(self):
        self.assertEqual(source_label(item('/m/F [Bluray-720p].mkv'), {'source_labels': {'bluray': 'BLU-RAY'}}), 'BLU-RAY')


if __name__ == '__main__':
    unittest.main()
