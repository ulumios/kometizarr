import gzip
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.rating_overlay.imdb_cache import ImdbRatingCache


class FakeResponse:
    def __init__(self, data):
        self.raw = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def raise_for_status(self):
        pass


class ImdbCacheTest(unittest.TestCase):
    def test_refresh_only_stores_requested_ids_and_preserves_last_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = ImdbRatingCache(Path(folder) / 'ratings.sqlite3')
            original = gzip.compress(b'tconst\taverageRating\tnumVotes\ntt100\t8.1\t10\ntt200\t5.0\t20\n')
            with patch('src.rating_overlay.imdb_cache.requests.get', return_value=FakeResponse(original)):
                self.assertEqual(cache.refresh({'tt100'}), {'tt100': 8.1})
            cache.mark_applied('Shows', '123', 'tt100', 8.1)
            self.assertEqual(cache.ratings({'tt100', 'tt200'}), {'tt100': 8.1})
            updated = gzip.compress(b'tconst\taverageRating\tnumVotes\ntt100\t8.2\t11\n')
            with patch('src.rating_overlay.imdb_cache.requests.get', return_value=FakeResponse(updated)):
                cache.refresh({'tt100'})
            self.assertEqual(cache.applied('Shows', '123'), ('tt100', 8.1))
            self.assertEqual(cache.ratings({'tt100'}), {'tt100': 8.2})
            with patch('src.rating_overlay.imdb_cache.requests.get', return_value=FakeResponse(b'invalid')):
                with self.assertRaises(OSError):
                    cache.refresh({'tt100'})
            self.assertEqual(cache.ratings({'tt100'}), {'tt100': 8.2})
            cache.close()


if __name__ == '__main__':
    unittest.main()
