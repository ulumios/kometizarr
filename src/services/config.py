"""Paths, saved settings and shared Plex helpers."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('kometizarr')

BACKUP_DIR = Path(os.getenv('KOMETIZARR_BACKUP_DIR', '/backups'))
SETTINGS_PATH = Path(os.getenv('KOMETIZARR_SETTINGS', '/app/kometizarr/data/settings.json'))
OVERLAY_OPTIONS = ('badge_style', 'badge_positions', 'rating_sources', 'media_overlay')


# Connection settings: entered in the web UI (settings.json) or, as before, environment variables
CONNECTIONS = {'plex_url': 'PLEX_URL', 'plex_token': 'PLEX_TOKEN', 'tmdb_api_key': 'TMDB_API_KEY',
               'omdb_api_key': 'OMDB_API_KEY', 'mdblist_api_key': 'MDBLIST_API_KEY'}
SECRETS = {'plex_token', 'tmdb_api_key', 'omdb_api_key', 'mdblist_api_key'}


def credential(name, settings=None):
    """A value saved in the web UI wins over the environment variable."""
    stored = ((settings if settings is not None else load_settings()).get('connections') or {}).get(name)
    return (stored or '').strip() or os.getenv(CONNECTIONS[name]) or None


def connections_view(settings):
    """What the UI may see: URLs in full, secrets only as set/unset with their last characters."""
    stored = settings.get('connections') or {}
    values, info = {}, {}
    for name, env in CONNECTIONS.items():
        own, from_env = (stored.get(name) or '').strip(), os.getenv(env) or ''
        effective = own or from_env
        values[name] = None if name in SECRETS else own
        info[name] = {'source': 'settings' if own else 'env' if from_env else None, 'env': env,
                      'hint': (f'…{effective[-4:]}' if len(effective) > 8 else 'gesetzt') if name in SECRETS and effective
                      else effective or None}
    return values, info


def merge_connections(stored, incoming):
    """None keeps the saved value, an empty string removes it (environment applies again)."""
    merged = dict(stored or {})
    for name, value in (incoming or {}).items():
        if name not in CONNECTIONS or value is None:
            continue
        if str(value).strip():
            merged[name] = str(value).strip()
        else:
            merged.pop(name, None)
    return merged


def plex_server(url=None, token=None):
    from plexapi.server import PlexServer
    settings = load_settings()
    return PlexServer(url or credential('plex_url', settings), token or credential('plex_token', settings))


def create_manager(library_name, rating_sources=None, badge_style=None, media_overlay=None,
                   api_cache=None):
    from src.rating_overlay.plex_poster_manager import PlexPosterManager
    settings = load_settings()
    return PlexPosterManager(
        plex_url=credential('plex_url', settings),
        plex_token=credential('plex_token', settings),
        library_name=library_name,
        tmdb_api_key=credential('tmdb_api_key', settings),
        omdb_api_key=credential('omdb_api_key', settings),
        mdblist_api_key=credential('mdblist_api_key', settings),
        backup_dir=str(BACKUP_DIR),
        dry_run=False,
        rating_sources=rating_sources,
        badge_style=badge_style,
        media_overlay=media_overlay,
        api_cache=api_cache,
    )


def design_for(settings, library_name):
    """The saved design of a library: its own profile, else the global design."""
    profile = (settings.get('library_profiles') or {}).get(library_name) or {}
    return {name: profile.get(name) or settings.get(name) for name in OVERLAY_OPTIONS}


def apply_saved_overlay_options(request, settings):
    """Every entry point (UI, cron, webhook, IMDb, conflicts) renders with the saved design
    of the library unless the caller sends its own options."""
    design = design_for(settings, request.library_name)
    for name in OVERLAY_OPTIONS:
        if name == 'badge_positions' and request.badge_position:
            continue  # explicit legacy unified badge
        if getattr(request, name) is None:
            setattr(request, name, design[name])
    return request


def backup_library_dir(library_name):
    """Resolve a library backup folder and refuse anything outside BACKUP_DIR."""
    root = BACKUP_DIR.resolve()
    folder = (BACKUP_DIR / library_name).resolve()
    if folder.parent != root:
        raise ValueError(f'Invalid library name: {library_name!r}')
    return folder


def selected_items(library, keys):
    """Resolve keys inside a library; selected seasons represent their episodes."""
    selected = []
    seen = set()
    for key in keys:
        item = library.fetchItem(int(key))
        if str(getattr(item, 'librarySectionID', library.key)) != str(library.key):
            raise ValueError(f"Item {key} does not belong to {library.title}")
        children = item.episodes() if item.type == 'season' else [item]
        for child in children:
            if child.type not in ('movie', 'show', 'episode'):
                continue
            if str(child.ratingKey) not in seen:
                selected.append(child)
                seen.add(str(child.ratingKey))
    return selected


def log_summary(title, total, counts, started_at):
    seconds = (datetime.now() - started_at).total_seconds()
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    duration = f'{hours}h {minutes}m {secs}s' if hours else f'{minutes}m {secs}s'
    logger.info("=" * 60)
    logger.info(f"✅ {title}")
    logger.info("-" * 60)
    logger.info(f"Total Items:     {total}")
    for name, value in counts.items():
        logger.info(f"{name + ':':<17}{value} ({value / total * 100 if total else 0:.1f}%)")
    logger.info(f"Duration:        {duration}")
    logger.info(f"Rate:            {total / (seconds / 60) if seconds > 0 else 0:.1f} items/min")
    logger.info("=" * 60)


DEFAULT_BADGE_POSITIONS = {
    "tmdb":        {"x": 2,  "y": 2},
    "imdb":        {"x": 2, "y": 2},
    "rt_critic":   {"x": 2,  "y": 78},
    "rt_audience": {"x": 70, "y": 78},
}

DEFAULT_BADGE_STYLE = {
    "individual_badge_size": 9,
    "font_size_multiplier": 1.0,
    "logo_size_multiplier": 2.0,
    "rating_color": "#FFFFFF",
    "background_opacity": 215,
    "font_family": "Liberation Sans Bold",
    "variant": "kometa",            # every badge exactly like Kometa's default overlays
    "top_logos": True,              # Kometa's Top images: IMDb Top 250, Certified Fresh, Verified Hot
    "kometa_scale": 100,            # percent of Kometa's size
}

DEFAULT_RATING_SOURCES = {
    "tmdb": False, "imdb": True, "rt_critic": False, "rt_audience": False,
}


def load_settings() -> dict:
    defaults = {
        "cron_normal": {"enabled": False, "libraries": [], "schedule": "0 3 * * *"},
        "cron_force":  {"enabled": False, "libraries": [], "schedule": "0 3 * * 0"},
        "webhook": {"enabled": False, "libraries": []},
        "imdb_direct": {"enabled": False, "libraries": [], "auto_fetch": False,
                        "auto_render": False, "hour": 4},
        "kometa_conflicts": {"auto_reset": False},
        "lost_overlay": "adopt",
        "library_profiles": {},
        "maintenance": {"plex_data_dir": "/plex"},
        "kometa": {"originals_dir": "", "library_map": {}},
        "media_overlay": {"source": True, "languages": True, "status": False, "label_size_percent": 4,
                           "episode_font_percent": 2.8, "font_percent": 4, "opacity": 180,
                           "source_labels": {"bluray": "BluRay", "prerelease": "PreRelease"},
                           "status_labels": {"airing": "Läuft gerade", "running": "Wird fortgesetzt",
                                             "ended": "Abgeschlossen", "canceled": "Abgesetzt"},
                           "status_position": {"x": 30, "y": 120}},
    }
    if not SETTINGS_PATH.exists():
        return defaults
    data = json.loads(SETTINGS_PATH.read_text())
    # Migrate old single-library format
    for key in ("cron_normal", "cron_force"):
        block = data.get(key, {})
        if "library" in block and "libraries" not in block:
            old = block.pop("library")
            block["libraries"] = [] if not old or old == "__all__" else [old]
    if "webhook" in data and "library" in data["webhook"] and "libraries" not in data["webhook"]:
        old = data["webhook"].pop("library")
        data["webhook"]["enabled"] = bool(old)
        data["webhook"]["libraries"] = [] if not old or old == "__all__" else [old]
    for key, value in defaults.items():
        data.setdefault(key, value)
    imdb_settings = data['imdb_direct'] or {}
    if 'auto_refresh' in imdb_settings:
        old_schedule = bool(imdb_settings.pop('auto_refresh'))
        imdb_settings.setdefault('auto_fetch', old_schedule)
        imdb_settings.setdefault('auto_render', old_schedule)
    data['imdb_direct'] = {**defaults['imdb_direct'], **imdb_settings}
    data['media_overlay'] = {**defaults['media_overlay'], **(data.get('media_overlay') or {})}
    labels = {**defaults['media_overlay']['status_labels'],
              **(data['media_overlay'].get('status_labels') or {})}
    if labels.get('running') == 'Läuft':
        labels['running'] = 'Wird fortgesetzt'
    data['media_overlay']['status_labels'] = labels
    return data


def save_settings(settings: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


def seed_defaults():
    """Store badge defaults so webhook and cron work before the UI was ever opened."""
    settings = load_settings()
    missing = {key: value for key, value in (('badge_positions', DEFAULT_BADGE_POSITIONS),
                                              ('badge_style', DEFAULT_BADGE_STYLE),
                                              ('rating_sources', DEFAULT_RATING_SOURCES))
               if key not in settings}
    if missing:
        settings.update(missing)
        save_settings(settings)
    return settings
