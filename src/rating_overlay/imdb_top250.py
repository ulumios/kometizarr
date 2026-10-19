"""Lists that switch a rating to Kometa's "Top" image.

- IMDb Top 250 (movies and TV), fetched like Kometa's imdb_chart builder → IMDbTop.png
- Rotten Tomatoes Certified Fresh / Verified Hot from Kometa's MDBList lists → RT-*-Top.png

Lists are cached for a day; when a source is unreachable the last known list is used."""

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


def _daily_list(key, load, minimum, cache_db=None):
    """IDs from ``load()``, cached for a day; the last known IDs when loading fails."""
    from src.rating_overlay.api_cache import ApiCache
    cache = ApiCache(cache_db) if cache_db else ApiCache()
    try:
        row = cache.db.execute('SELECT value, fetched_at FROM api_cache WHERE key=?', (key,)).fetchone()
        stored = json.loads(row[0]) if row and row[0] else None
        if stored and time.time() - row[1] < MAX_AGE:
            return set(stored)
        try:
            ids = load()
            if len(ids) < minimum:  # refuse a truncated answer
                raise ValueError(f'unexpected list size {len(ids)}')
        except Exception as exc:
            logger.warning('%s not available (%s); using %s', key, exc,
                           'the last known list' if stored else 'no marker')
            return set(stored or [])
        with cache.db:
            cache.db.execute('INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)', (key, json.dumps(ids), time.time()))
        return set(ids)
    finally:
        cache.close()


def top250_ids(cache_db=None, fetch=fetch_chart):
    """Set of IMDb IDs in the movie and TV Top 250 (both charts have 250 entries)."""
    return _daily_list('imdb-top250', lambda: [i for chart in CHARTS.values() for i in fetch(chart)],
                       400, cache_db)


# Kometa marks Certified Fresh / Verified Hot with these MDBList lists (ratings.yml mdblist_top)
RT_LISTS = {'rt_critic': ('certifiedfreshmovies', 'certifiedfreshshows'),
            'rt_audience': ('verifiedhotmovies', 'verifiedhotshows')}


def fetch_mdblist(name, session=requests):
    response = session.get(f'https://mdblist.com/lists/k0meta/{name}/json', timeout=20,
                           headers={'User-Agent': 'Kometizarr'})
    response.raise_for_status()
    return [entry['imdb_id'] for entry in response.json() if entry.get('imdb_id')]


def rt_top_ids(cache_db=None, fetch=fetch_mdblist):
    """{'rt_critic': Certified Fresh IDs, 'rt_audience': Verified Hot IDs}."""
    return {source: _daily_list(f'rt-top:{source}', lambda names=names: [i for n in names for i in fetch(n)],
                                10, cache_db)
            for source, names in RT_LISTS.items()}
