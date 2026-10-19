"""Sonarr/Radarr webhooks: find the imported title in Plex and render it.

The *arr apps report an import before Plex has scanned the file, so the task waits and is
retried a few times until Plex knows the title."""

import asyncio
import logging

from src.services import config, overlay, tasks
from src.services.models import ProcessRequest
from src.services.progress import progress

logger = logging.getLogger('kometizarr')

FIRST_DELAY = 120
RETRY_DELAY = 300
MAX_ATTEMPTS = 6


def parse(data):
    """Target from a Radarr/Sonarr payload, or None for events that need no render."""
    if data.get('eventType') not in ('Download', 'MovieFileImported', 'EpisodeFileImported'):
        return None
    if data.get('movie'):
        movie = data['movie']
        return {'type': 'movie', 'title': movie.get('title'), 'ids': {
            'imdb': movie.get('imdbId'), 'tmdb': movie.get('tmdbId')}, 'episodes': []}
    if data.get('series'):
        series = data['series']
        episodes = [[e.get('seasonNumber'), e.get('episodeNumber')] for e in data.get('episodes') or []
                    if e.get('seasonNumber') is not None and e.get('episodeNumber') is not None]
        return {'type': 'show', 'title': series.get('title'), 'ids': {
            'imdb': series.get('imdbId'), 'tvdb': series.get('tvdbId'), 'tmdb': series.get('tmdbId')},
            'episodes': episodes}
    return None


def resolve(target, libraries):
    """(library name, [rating keys]) for the target, or None while Plex does not know it."""
    from plexapi.exceptions import NotFound
    server = config.plex_server()
    for library in server.library.sections():
        if library.type != target['type'] or (libraries and library.title not in libraries):
            continue
        for scheme in ('imdb', 'tmdb', 'tvdb'):
            value = target['ids'].get(scheme)
            if not value:
                continue
            try:
                item = library.getGuid(f'{scheme}://{value}')
            except NotFound:
                continue
            keys = [str(item.ratingKey)]
            for season, number in target['episodes']:
                try:
                    keys.append(str(item.episode(season=season, episode=number).ratingKey))
                except NotFound:
                    return None  # the show is there, the new episode not yet
            return library.title, keys
    return None


@tasks.handler('arr')
async def arr_task(task):
    payload = task['payload']
    target, attempt = payload['target'], payload.get('attempt', 1)
    progress.phase = f"Suche „{target['title']}“ in Plex"
    webhook = config.load_settings().get('webhook', {})
    found = await asyncio.to_thread(resolve, target, webhook.get('libraries') or [])
    if found is None:
        if attempt >= MAX_ATTEMPTS:
            return f"„{target['title']}“ nach {attempt} Versuchen nicht in Plex gefunden"
        retry = await tasks.enqueue('arr', {**payload, 'attempt': attempt + 1}, delay=RETRY_DELAY)
        progress.phase = f'Noch nicht in Plex – erneuter Versuch als Aufgabe #{retry}'
        return None
    library, keys = found
    progress.library = library
    await overlay.run_overlay(ProcessRequest(library_name=library, rating_keys=keys, record_results=True))
    return progress.error or (f'{progress.failed} Poster fehlgeschlagen' if progress.failed else None)
