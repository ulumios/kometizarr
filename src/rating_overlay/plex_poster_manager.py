"""
Plex Poster Manager - Apply rating overlays to Plex library

Integrates all components: backup, rating fetch, overlay, upload
MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from plexapi.server import PlexServer
from plexapi.library import LibrarySection

from .backup_manager import PosterBackupManager
from .rating_fetcher import RatingFetcher
from .badge_generator import BadgeGenerator
from .overlay_composer import OverlayComposer
from .multi_rating_badge import MultiRatingBadge
from .media_badges import source_label, audio_languages, draw_media_badges, episode_overlay_options, prepare_episode_canvas, prepare_canvas, show_status_label
from ..utils.logger import ProgressTracker, print_header, print_subheader, print_summary

logger = logging.getLogger(__name__)

# Bump when the drawing code changes in a way that should re-render every poster.
RENDERER_VERSION = 1


class PlexPosterManager:
    """Apply rating overlays to Plex posters with automatic backup"""

    def __init__(
        self,
        plex_url: str,
        plex_token: str,
        library_name: str,
        tmdb_api_key: str,
        omdb_api_key: Optional[str] = None,
        mdblist_api_key: Optional[str] = None,
        backup_dir: str = './data/kometizarr_backups',
        badge_style: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        rating_sources: Optional[Dict[str, bool]] = None,
        media_overlay: Optional[Dict[str, Any]] = None,
        api_cache=None
    ):
        """
        Initialize Plex poster manager

        Args:
            plex_url: Plex server URL
            plex_token: Plex authentication token
            library_name: Library name (e.g., 'Movies')
            tmdb_api_key: TMDB API key
            omdb_api_key: Optional OMDb API key
            backup_dir: Directory for poster backups
            badge_style: Optional dict with styling options (size, font, color, opacity)
            dry_run: If True, preview operations without applying
            rating_sources: Optional dict to control which ratings to show
                           e.g. {'tmdb': True, 'imdb': True, 'rt_critic': False, 'rt_audience': False}
                           If None, shows all available ratings
        """
        self.plex_url = plex_url
        self.plex_token = plex_token
        self.library_name = library_name
        self.dry_run = dry_run
        self.rating_sources = rating_sources or {}
        self.badge_style = badge_style or {}  # Store badge styling options
        self.media_overlay = media_overlay or {}
        self.imdb_ratings = {}  # Official IMDb dataset values, when enabled and cached
        self.last_problem = None

        # Connect to Plex
        self.server = PlexServer(plex_url, plex_token)
        self.library = self.server.library.section(library_name)

        # Initialize components
        self.backup_manager = PosterBackupManager(backup_dir)
        self.rating_fetcher = RatingFetcher(tmdb_api_key, omdb_api_key, mdblist_api_key, cache=api_cache)
        # BadgeGenerator is legacy (old unified badge), badge_style is now a dict for MultiRatingBadge
        self.badge_generator = BadgeGenerator(style='default')
        self.overlay_composer = OverlayComposer(self.badge_generator)
        self.multi_rating_badge = MultiRatingBadge()  # New multi-source badge (uses badge_style dict)

        # Temp directory for processing
        self.temp_dir = Path('/tmp/kometizarr_temp')
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Connected to Plex: {self.server.friendlyName}")
        logger.info(f"Library: {library_name}")
        if dry_run:
            logger.info("DRY-RUN MODE: No changes will be applied")

    def _extract_tmdb_id(self, guids: list) -> Optional[int]:
        """Extract TMDB ID from Plex GUIDs"""
        for guid in guids:
            if 'tmdb://' in guid.id:
                return int(guid.id.split('tmdb://')[1])
        return None

    def _extract_imdb_id(self, guids: list) -> Optional[str]:
        """Extract IMDb ID from Plex GUIDs"""
        for guid in guids:
            if 'imdb://' in guid.id:
                return guid.id.split('imdb://')[1]
        return None

    def _extract_plex_ratings(self, movie) -> Dict[str, float]:
        """
        Extract ratings from Plex's own metadata

        Plex stores ratings from multiple sources in the ratings array:
        - TMDB (audience, 0-10 scale)
        - IMDb (audience, 0-10 scale)
        - RT Critic (critic, 0-10 scale -> multiply by 10 for %)
        - RT Audience (audience, 0-10 scale -> multiply by 10 for %)

        Returns:
            Dict with available ratings: {'tmdb': 7.5, 'imdb': 6.8, 'rt_critic': 30.0, 'rt_audience': 92.0}
        """
        plex_ratings = {}

        if hasattr(movie, 'ratings'):
            for rating in movie.ratings:
                rating_type = rating.type
                rating_value = rating.value
                rating_image = rating.image if hasattr(rating, 'image') else ''

                # RT Critic (critic type with RT image)
                if rating_type == 'critic' and 'rottentomatoes' in rating_image:
                    plex_ratings['rt_critic'] = rating_value * 10  # Convert 0-10 to 0-100%

                # RT Audience (audience type with RT image)
                elif rating_type == 'audience' and 'rottentomatoes' in rating_image:
                    plex_ratings['rt_audience'] = rating_value * 10  # Convert 0-10 to 0-100%

                # IMDb (audience type with imdb image)
                elif rating_type == 'audience' and 'imdb' in rating_image:
                    plex_ratings['imdb'] = rating_value

                # TMDB (audience type with themoviedb image)
                elif rating_type == 'audience' and 'themoviedb' in rating_image:
                    plex_ratings['tmdb'] = rating_value

        return plex_ratings

    def collect_inputs(self, item, badge_positions=None, position='northwest') -> Dict[str, Any]:
        """Everything that decides how the poster looks, gathered without rendering.

        ``problem`` is set to (counter, reason) when there is nothing to render."""
        episode = getattr(item, 'type', None) == 'episode'
        guids = getattr(item, 'guids', []) or []
        tmdb_id = self._extract_tmdb_id(guids)
        imdb_id = self._extract_imdb_id(guids)
        inputs = {'episode': episode, 'position': position, 'problem': None}
        if not episode and not tmdb_id and not imdb_id:
            inputs['problem'] = ('failed', 'Keine TMDB- oder IMDb-ID')
            return inputs

        ratings = self._extract_plex_ratings(item)
        if imdb_id in self.imdb_ratings:
            ratings['imdb'] = self.imdb_ratings[imdb_id]
        if not episode:
            # API fallbacks only for what Plex does not carry (answers are cached)
            if 'tmdb' not in ratings and tmdb_id:
                media_type = 'tv' if self.library.type == 'show' else 'movie'
                data = self.rating_fetcher.fetch_tmdb_rating(tmdb_id, media_type=media_type)
                if data and data.get('rating', 0) > 0:
                    ratings['tmdb'] = data['rating']
            if imdb_id and 'imdb' not in ratings:
                data = self.rating_fetcher.fetch_omdb_rating(imdb_id)
                try:
                    ratings['imdb'] = float(data['imdb_rating'])
                except (TypeError, KeyError, ValueError):
                    pass
            if imdb_id and ('rt_critic' not in ratings or 'rt_audience' not in ratings):
                data = self.rating_fetcher.fetch_mdblist_rating(imdb_id) or {}
                for key in ('rt_critic', 'rt_audience'):
                    if key not in ratings and data.get(key):
                        ratings[key] = data[key]
        ratings = {k: v for k, v in ratings.items() if self.rating_sources.get(k, True) and v}

        media = self.media_overlay
        source = source_label(item, media) if media.get('source', False) else None
        languages = audio_languages(item) if episode and media.get('languages', False) else []
        status = None
        if getattr(item, 'type', None) == 'show' and media.get('status', False) and tmdb_id:
            status = show_status_label(self.rating_fetcher.fetch_tmdb_status(tmdb_id), media)
        style, positions = self.badge_style, badge_positions
        if episode:
            style, positions, media = episode_overlay_options(style, positions, media)
        inputs.update(ratings=ratings, source=source, languages=languages, status=status,
                      style=style, positions=positions, media=media)
        if not ratings and not (source or languages or status):
            inputs['problem'] = (('skipped', 'Keine Wertungen oder Badges') if episode
                                 else ('failed', 'Keine Wertungen verfügbar'))
        return inputs

    @staticmethod
    def render_hash(inputs, original_path=None) -> str:
        """Fingerprint of the rendered result: inputs, original image and renderer version."""
        import hashlib
        import json
        digest = hashlib.sha256()
        digest.update(f'renderer:{RENDERER_VERSION}'.encode())
        digest.update(json.dumps({k: v for k, v in inputs.items() if k != 'problem'},
                                 sort_keys=True, default=str).encode())
        if original_path is not None and Path(original_path).is_file():
            digest.update(Path(original_path).read_bytes())
        return digest.hexdigest()

    def render_image(self, original, output, inputs):
        """Compose overlay image from an original backup according to inputs."""
        from PIL import Image
        output = Path(output)
        canvas = output.with_name(output.stem + '.canvas.jpg')
        try:
            if inputs['episode']:
                prepare_episode_canvas(original, canvas)
            else:
                prepare_canvas(original, canvas)
            if inputs['ratings']:
                self.multi_rating_badge.apply_to_poster(
                    poster_path=str(canvas), ratings=inputs['ratings'], output_path=str(output),
                    position=inputs['position'], badge_style=inputs['style'],
                    badge_positions=inputs['positions'])
            else:
                with Image.open(canvas) as img:
                    img.convert('RGB').save(output, 'JPEG', quality=95)
            if inputs['source'] or inputs['languages'] or inputs['status']:
                draw_media_badges(str(output), inputs['source'], inputs['languages'], inputs['media'],
                                  status=inputs['status'], badge_style=inputs['style'])
        finally:
            canvas.unlink(missing_ok=True)

    def process_movie(
        self,
        movie,
        position: str = 'northwest',
        force: bool = False,
        badge_positions: Optional[Dict[str, Dict[str, float]]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Optional[bool]:
        """
        Backup, render and upload one movie, show or episode.

        Returns True if uploaded, None if skipped (already has overlay or nothing to show),
        False if failed. ``self.last_problem`` holds the reason for None/False.
        """
        self.last_problem = None
        try:
            if not force and self.backup_manager.has_overlay(self.library_name, movie):
                self.last_problem = 'Overlay bereits vorhanden'
                return None
            inputs = inputs or self.collect_inputs(movie, badge_positions, position)
            if inputs['problem']:
                counter, self.last_problem = inputs['problem']
                logger.warning(f"⚠️  {movie.title}: {self.last_problem}")
                return None if counter == 'skipped' else False

            logger.info(f"Processing: {movie.title} (Ratings: {inputs['ratings']})")
            if self.dry_run:
                return True

            if inputs['episode']:
                source = getattr(movie, 'thumb', None)
                source = self.server.url(source, includeToken=True) if source else None
            else:
                source = movie.posterUrl
            if not source:
                self.last_problem = 'Kein Poster in Plex'
                return False
            original = self.backup_manager.backup_poster(
                self.library_name, movie, source, self.plex_token,
                metadata={'ratings': inputs['ratings']})
            if not original:
                self.last_problem = 'Original konnte nicht gesichert werden'
                return False

            _, overlay = self.backup_manager.item_paths(self.library_name, movie)
            pending = overlay.with_name(f'.{movie.ratingKey}-overlay.pending.jpg')
            try:
                self.render_image(original, pending, inputs)
                movie.uploadPoster(filepath=str(pending))
                pending.replace(overlay)
            finally:
                pending.unlink(missing_ok=True)
            logger.info(f"✓ {movie.title}: overlay applied ({inputs['ratings']})")
            return True
        except Exception as e:
            logger.exception(f"✗ {movie.title}: Error - {e}")
            self.last_problem = str(e)
            return False

    def process_library(
        self,
        limit: Optional[int] = None,
        position: str = 'northwest',
        force: bool = False,
        rate_limit: float = 0.3
    ) -> Dict[str, int]:
        """
        Process entire library with rating overlays

        Args:
            limit: Max number of movies to process (None = all)
            position: Badge position
            force: Force reprocessing
            rate_limit: Delay between requests (seconds)

        Returns:
            Dict with statistics
        """
        all_movies = self.library.all()
        total = len(all_movies)

        if limit:
            all_movies = all_movies[:limit]
            print_header(f"Processing {limit} of {total} Movies")
        else:
            print_header(f"Processing All {total} Movies")

        # Initialize progress tracker
        progress = ProgressTracker(len(all_movies), "Applying rating overlays")
        start_time = time.time()

        print(f"Library: {self.library_name}")
        print(f"Backup Dir: {self.backup_manager.backup_dir}")
        print(f"Position: {position}")
        print(f"Force Reprocess: {force}")
        print()

        for i, movie in enumerate(all_movies, 1):
            # Show progress
            print_subheader(f"{progress.get_progress_str()} | {movie.title}")

            result = self.process_movie(movie, position=position, force=force)

            # Update progress based on result
            if result is None:
                # None = skipped (already has overlay)
                progress.update(skipped=True)
            elif result:
                # True = success
                progress.update(success=True)
            else:
                # False = failed
                progress.update(success=False)

            # Show current stats
            print(f"  {progress.get_stats_str()}")

            # Rate limiting (respect TMDB limits)
            time.sleep(rate_limit)

        elapsed = time.time() - start_time

        # Final summary
        stats = {
            'Total Movies': len(all_movies),
            'Successfully Processed': progress.success,
            'Skipped (Already Done)': progress.skipped,
            'Failed': progress.failed,
            'Total Time': f"{elapsed:.1f}s ({elapsed/60:.1f}min)",
            'Average Speed': f"{elapsed/len(all_movies):.2f}s per movie",
            'Processing Rate': f"{len(all_movies)/elapsed:.2f} movies/sec"
        }

        print_summary(stats)

        return {
            'total': len(all_movies),
            'success': progress.success,
            'skipped': progress.skipped,
            'failed': progress.failed,
            'elapsed': elapsed
        }

    def restore_movie(self, movie_title: str) -> bool:
        """Restore the original poster of one title (CLI helper)."""
        try:
            movie = self.library.get(movie_title)
        except Exception:
            logger.error(f"Movie not found: {movie_title}")
            return False
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would restore original poster for '{movie_title}'")
            return True
        return self.backup_manager.restore_original(self.library_name, movie)

    def restore_library(self) -> int:
        """Restore every original poster of this library that currently shows an overlay."""
        restored = 0
        for item in self.library.all():
            if self.backup_manager.has_overlay(self.library_name, item) and (
                    self.dry_run or self.backup_manager.restore_original(self.library_name, item)):
                restored += 1
        logger.info(f"✓ Restored {restored} posters")
        return restored

    def list_backups(self) -> List[Dict]:
        """List all backed up posters"""
        return self.backup_manager.list_backups(library_name=self.library_name)


def main():
    """Example usage"""
    import json
    import argparse
    from ..utils.logger import setup_logger

    # Parse arguments
    parser = argparse.ArgumentParser(description='Kometizarr Plex Poster Manager')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Preview without applying')
    parser.add_argument('--limit', type=int, help='Limit number of movies to process')
    parser.add_argument('--force', action='store_true', help='Force reprocess all movies')
    parser.add_argument('--restore', action='store_true', help='Restore original posters')
    parser.add_argument('--restore-movie', type=str, help='Restore specific movie')
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config = json.load(f)

    # Setup better logging
    setup_logger('kometizarr', level=logging.INFO)

    # Initialize manager
    manager = PlexPosterManager(
        plex_url=config['plex']['url'],
        plex_token=config['plex']['token'],
        library_name=config['plex']['library'],
        tmdb_api_key=config['apis']['tmdb']['api_key'],
        omdb_api_key=config['apis'].get('omdb', {}).get('api_key'),
        mdblist_api_key=config['apis'].get('mdblist', {}).get('api_key'),
        backup_dir=config['output']['directory'],
        badge_style=config['rating_overlay']['badge'].get('style', 'default'),
        dry_run=args.dry_run,
        rating_sources=config['rating_overlay'].get('sources', None)
    )

    # Restore mode
    if args.restore:
        manager.restore_library()
        return

    if args.restore_movie:
        manager.restore_movie(args.restore_movie)
        return

    # Process library
    if config['rating_overlay']['enabled']:
        position = config['rating_overlay']['badge'].get('position', 'northeast')

        manager.process_library(
            limit=args.limit,
            position=position,
            force=args.force
        )


if __name__ == '__main__':
    main()
