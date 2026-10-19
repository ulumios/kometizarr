"""IMDb Top 250 (movies and TV shows), fetched like Kometa's imdb_chart builder.

Kometa shows rating/IMDbTop.png instead of rating/IMDb.png for these titles. The lists are
cached for a day; when IMDb is unreachable the last known lists are used."""

import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

GRAPHQL_URL = 'https://api.graphql.imdb.com/'
CHARTS = {'movie': 'TOP_RATED_MOVIES', 'show': 'TOP_RATED_TV_SHOWS'}
MAX_AGE = 24 * 3600


def fetch_chart(chart_type, session=requests):
    query = '{ chartTitles(chart: { chartType: %s }, first: 250) { edges { node { id } } } }' % chart_type
    response = session.post(GRAPHQL_URL, json={'query': query}, timeout=20,
                            headers={'content-type': 'application/json', 'x-imdb-client-name': 'imdb-web-next'})
    response.raise_for_status()
    edges = response.json()['data']['chartTitles']['edges']
    return [edge['node']['id'] for edge in edges]


def top250_ids(cache_db=None, fetch=fetch_chart):
    """Set of IMDb IDs in the movie and TV Top 250; never raises."""
    from src.rating_overlay.api_cache import ApiCache
    cache = ApiCache(cache_db) if cache_db else ApiCache()
    try:
        row = cache.db.execute("SELECT value, fetched_at FROM api_cache WHERE key='imdb-top250'").fetchone()
        stored = json.loads(row[0]) if row and row[0] else None
        if stored and time.time() - row[1] < MAX_AGE:
            return set(stored)
        try:
            ids = [imdb_id for chart in CHARTS.values() for imdb_id in fetch(chart)]
            if len(ids) < 400:  # both charts have 250 entries; refuse a truncated answer
                raise ValueError(f'unexpected IMDb chart size {len(ids)}')
        except Exception as exc:
            logger.warning('IMDb Top 250 not available (%s); using %s', exc,
                           'the last known lists' if stored else 'no Top 250 marker')
            return set(stored or [])
        with cache.db:
            cache.db.execute('INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)',
                             ('imdb-top250', json.dumps(ids), time.time()))
        return set(ids)
    finally:
        cache.close()
