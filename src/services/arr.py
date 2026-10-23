"""Sonarr/Radarr webhooks: find the imported title in Plex and render it.

The *arr apps report an import before Plex has scanned the file, so the task waits and is
retried a few times until Plex knows the title. On an upgrade the title already exists, so
the task also waits until Plex shows the new file (and asks Plex to scan that folder);
otherwise it would read the old file's languages and source."""

import asyncio
import logging

from src.services import config, overlay, tasks
from src.services.models import ProcessRequest
from src.services.progress import progress

logger = logging.getLogger('kometizarr')

FIRST_DELAY = 120
RETRY_DELAY = 300
SCAN_DELAY = 90  # after asking Plex to scan the folder
MAX_ATTEMPTS = 6


def _name(path):
    """File name of a path from Sonarr/Radarr or Plex, Windows or POSIX."""
    return str(path or '').replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]


def _folder(path):
    path = str(path or '')
    cut = max(path.rfind('/'), path.rfind('\\'))
    return path[:cut] if cut > 0 else None


def _files(data):
    """Names of the imported files: new or upgraded episode/movie files."""
    entries = [data.get('episodeFile'), data.get('movieFile'), *(data.get('episodeFiles') or [])]
    return sorted({_name(entry.get('relativePath') or entry.get('path'))
                   for entry in entries if isinstance(entry, dict) and (entry.get('relativePath') or entry.get('path'))})


def parse(data):
    """Target from a Radarr/Sonarr payload, or None for events that need no render."""
    if data.get('eventType') not in ('Download', 'MovieFileImported', 'EpisodeFileImported'):
        return None
    if data.get('movie'):
        movie = data['movie']
        return {'type': 'movie', 'title': movie.get('title'), 'ids': {
            'imdb': movie.get('imdbId'), 'tmdb': movie.get('tmdbId')}, 'episodes': [],
            'files': _files(data), 'upgrade': bool(data.get('isUpgrade'))}
    if data.get('series'):
        series = data['series']
        episodes = [[e.get('seasonNumber'), e.get('episodeNumber')] for e in data.get('episodes') or []
                    if e.get('seasonNumber') is not None and e.get('episodeNumber') is not None]
        return {'type': 'show', 'title': series.get('title'), 'ids': {
            'imdb': series.get('imdbId'), 'tvdb': series.get('tvdbId'), 'tmdb': series.get('tmdbId')},
            'episodes': episodes, 'files': _files(data), 'upgrade': bool(data.get('isUpgrade'))}
    return None


def _plex_files(item):
    return [getattr(part, 'file', '') or '' for media in getattr(item, 'media', []) or []
            for part in getattr(media, 'parts', []) or []]


def resolve(target, libraries):
    """(library name, [rating keys], folders) for the target, or None while Plex does not
    know it. ``folders`` is non-empty while Plex still shows another file than the one
    imported: these Plex folders should be scanned before rendering."""
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
            keys, media_items = [str(item.ratingKey)], [item] if target['type'] == 'movie' else []
            for season, number in target['episodes']:
                try:
                    episode = item.episode(season=season, episode=number)
                except NotFound:
                    return None  # the show is there, the new episode not yet
                keys.append(str(episode.ratingKey))
                media_items.append(episode)
            plex_files = [path for media_item in media_items for path in _plex_files(media_item)]
            wanted = set(target.get('files') or [])
            folders = []
            if wanted and plex_files and not wanted & {_name(path) for path in plex_files}:
                folders = sorted({folder for folder in map(_folder, plex_files) if folder})
            return library.title, keys, folders
    return None


def scan_folders(library, folders):
    """Ask Plex to scan only these folders (a partial scan, like Sonarr's Plex connection)."""
    section = config.plex_server().library.section(library)
    for folder in folders:
        try:
            section.update(path=folder)
        except Exception:
            logger.exception('Plex scan of %s failed', folder)


@tasks.handler('arr')
async def arr_task(task):
    payload = task['payload']
    target, attempt = payload['target'], payload.get('attempt', 1)
    progress.phase = f"Suche „{target['title']}“ in Plex"
    webhook = config.load_settings().get('webhook', {})
    found = await asyncio.to_thread(resolve, target, webhook.get('libraries') or [])
    if found is not None and found[2]:
        library, _, folders = found
        if attempt >= MAX_ATTEMPTS:
            return f"Plex zeigt für „{target['title']}“ nach {attempt} Versuchen noch die alte Datei"
        await asyncio.to_thread(scan_folders, library, folders)
        retry = await tasks.enqueue('arr', {**payload, 'attempt': attempt + 1}, delay=SCAN_DELAY)
        progress.phase = f'Plex kennt die neue Datei noch nicht – Ordner wird gescannt, erneuter Versuch als Aufgabe #{retry}'
        return None
    if found is None:
        if attempt >= MAX_ATTEMPTS:
            return f"„{target['title']}“ nach {attempt} Versuchen nicht in Plex gefunden"
        retry = await tasks.enqueue('arr', {**payload, 'attempt': attempt + 1}, delay=RETRY_DELAY)
        progress.phase = f'Noch nicht in Plex – erneuter Versuch als Aufgabe #{retry}'
        return None
    library, keys, _ = found
    progress.library = library
    await overlay.run_overlay(ProcessRequest(library_name=library, rating_keys=keys, record_results=True))
    return progress.error or (f'{progress.failed} Poster fehlgeschlagen' if progress.failed else None)
