"""Restoring originals and resetting items to their Plex agent poster."""

import asyncio
import logging
import shutil

from src.services import config, conflicts, library_index, overlay, tasks
from src.services.models import ProcessRequest
from src.services.progress import progress, publish

logger = logging.getLogger('kometizarr')


async def run_restore(request):
    """Upload originals again, or reset to the Plex agent poster (reset_to_plex)."""
    try:
        progress.begin_items('restore', library=request.library_name)
        await publish()

        from src.rating_overlay.backup_manager import PosterBackupManager
        from src.rating_overlay.poster_storage import paths

        server = config.plex_server()
        library = server.library.section(request.library_name)
        backup_manager = PosterBackupManager(backup_dir=str(config.BACKUP_DIR))

        if request.rating_keys:
            all_items = config.selected_items(library, request.rating_keys)
        else:
            all_items = library.all()
            if request.include_episodes and library.type == 'show':
                all_items += library.all(libtype='episode')
        if request.limit:
            all_items = all_items[:request.limit]

        progress.total = len(all_items)

        logger.info(f"🔄 Restore started: {request.library_name} ({len(all_items)} items)")

        for i, item in enumerate(all_items, 1):
            if progress.stop_requested:
                logger.info(f"Stop requested - stopping restore at item {i}/{progress.total}")
                break

            progress.done = i
            progress.current = item.title

            if request.reset_to_plex:
                outcome = reset_to_plex_poster(request.library_name, item, server, backup_manager)
            # Skip if no backup exists or the original is already shown
            elif not all(path.is_file() for path in paths(backup_manager, request.library_name, item)):
                outcome = 'skipped'
            elif backup_manager.restore_original(request.library_name, item):
                outcome = 'restored'
            else:
                outcome = 'failed'

            progress.count('success' if outcome == 'restored' else outcome, item.ratingKey)
            if outcome == 'restored':
                library_index.invalidate_browse_poster(request.library_name, item.ratingKey)
                overlay.mark_item(request.library_name, item, status='original', reason=None)
                # a reset to the agent poster also removed Kometa's label
                library_index.set_flags(request.library_name, item.ratingKey, has_overlay=False,
                                        kometa_label=False if request.reset_to_plex else None)
            await publish()

            # Rate limiting
            await asyncio.sleep(0.1)

        config.log_summary(f"Restore Completed: {request.library_name}", progress.total,
                           {'Restored': progress.success, 'Failed': progress.failed,
                            'Skipped': progress.skipped}, progress.items_started_at)

    except Exception as e:
        progress.error = str(e)
        logger.exception(f"❌ Restore failed: {request.library_name}")
    finally:
        progress.end_items()
        await publish(force=True)


def reset_to_plex_poster(library_name, item, server, backup_manager):
    """Single reset path for the library browser, conflicts and 'Fetch Fresh Posters':
    select the Plex agent poster, re-capture it as the clean original and hand the item
    back from Kometa (label removed) so the next overlay run starts from clean artwork."""
    from src.rating_overlay.kometa_conflicts import ManualPosterQueue, remove_overlay_label, select_agent_poster
    from src.rating_overlay.poster_storage import capture_plex
    try:
        if not select_agent_poster(item):
            return 'skipped'
        # Selecting artwork in Plex happens first; replacing the backup
        # happens only after the new image is fetched and validated.
        capture_plex(backup_manager, library_name, item, server, config.credential('plex_token'))
        old_episode = backup_manager.backup_dir / library_name / 'episodes' / str(item.ratingKey)
        if item.type == 'episode' and old_episode.is_dir():
            shutil.rmtree(old_episode)
        remove_overlay_label(item)
        ManualPosterQueue().remove(library_name, item)
        overlay.record_poster_origin(library_name, item, 'agent')
        conflicts.forget(library_name, item.ratingKey)
        library_index.invalidate_browse_poster(library_name, item.ratingKey)
        library_index.cache_backup_artwork(library_name, item, backup_manager, False)
        return 'restored'
    except Exception:
        logger.exception('Failed to reset Plex poster for %s', item.ratingKey)
        return 'failed'


@tasks.handler('restore')
@tasks.handler('fresh_posters')
async def restore_task(task):
    await run_restore(ProcessRequest(**task['payload']))
    if progress.error:
        return progress.error
    return f'{progress.failed} Poster fehlgeschlagen' if progress.failed else None
