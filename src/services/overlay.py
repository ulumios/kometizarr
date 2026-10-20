"""Overlay runs: facts → plan (decision.py) → preparation → render → item state."""

import asyncio
import logging
import time
from pathlib import Path

from src.services import config, conflicts, library_index, tasks
from src.services.progress import progress, publish

logger = logging.getLogger('kometizarr')


def backup_clean_plex_poster(manager, item):
    """Verify and replace one original without deleting a usable prior image."""
    from src.rating_overlay.poster_storage import capture_plex
    try:
        capture_plex(manager.backup_manager, manager.library_name,
                     item, manager.server, manager.plex_token)
        return True
    except Exception:
        logger.exception('Could not cache Plex poster %s', item.ratingKey)
        return False


def record_poster_origin(library_name, item, source):
    from src.rating_overlay.item_state import ItemState
    from src.rating_overlay.poster_storage import backup_id
    with ItemState() as store:
        store.update(library_name, item, original_source=source, backup_id=backup_id(item))


def mark_item(library_name, item, **fields):
    """Record the outcome for one item in item_state; never breaks a running task."""
    try:
        from src.rating_overlay.item_state import ItemState
        from src.rating_overlay.poster_storage import backup_id
        with ItemState() as store:
            store.update(library_name, item, backup_id=backup_id(item), **fields)
    except Exception:
        logger.exception('Could not record state for %s', getattr(item, 'ratingKey', '?'))


def item_row(library_name, item):
    from src.rating_overlay.item_state import ItemState
    with ItemState() as store:
        return store.get(library_name, item.ratingKey)


def overlay_lost(library_name, item, row):
    """True when our uploaded poster is no longer the one Plex shows.

    The thumb URL changes with the selected artwork; only then are the posters fetched."""
    thumb = getattr(item, 'thumb', None)
    if row.get('status') != 'rendered' or not row.get('uploaded_thumb') or not thumb \
            or thumb == row['uploaded_thumb']:
        return False
    try:
        selected = next((p for p in item.posters() if getattr(p, 'selected', False)), None)
    except Exception:
        logger.exception('Could not read posters of %s', item.ratingKey)
        return False
    key = str(getattr(selected, 'ratingKey', '') or '')
    lost = key != row['uploaded_poster'] if row.get('uploaded_poster') else 'upload' not in key
    if not lost:  # same poster, only the URL changed: remember it to skip this check next time
        mark_item(library_name, item, uploaded_thumb=thumb)
    return lost


def uploaded_identity(item):
    """Thumb and selected poster key right after our upload (see overlay_lost)."""
    try:
        item.reload()
        selected = next((p for p in item.posters() if getattr(p, 'selected', False)), None)
        return {'uploaded_thumb': getattr(item, 'thumb', None),
                'uploaded_poster': str(selected.ratingKey) if selected else None}
    except Exception:
        logger.exception('Could not read uploaded poster of %s', getattr(item, 'ratingKey', '?'))
        return {}


def run_preparation_step(step, manager, manual_queue, item):
    """Execute one step planned by decision.plan_item; False when it could not be done."""
    from src.rating_overlay.kometa_conflicts import select_agent_poster
    if step == 'capture_manual':
        if not backup_clean_plex_poster(manager, item):
            return False
        manual_queue.remove(manager.library_name, item)
        return True
    if step in ('capture_current', 'capture_if_missing'):
        return backup_clean_plex_poster(manager, item)
    if step == 'reset_agent':
        return select_agent_poster(item) and backup_clean_plex_poster(manager, item)
    if step == 'use_kometa_original':
        return adopt_kometa_original(manager, item)
    raise ValueError(f'Unknown step {step}')


def adopt_kometa_original(manager, item):
    """Use Kometa's stored clean poster as our original (read-only on Kometa's side)."""
    from src.rating_overlay.kometa_originals import as_jpeg, find_original
    from src.rating_overlay.poster_storage import replace_image, write_metadata
    source = find_original(config.load_settings(), manager.library_name, item.ratingKey)
    if source is None:
        return False
    try:
        original, overlay = manager.backup_manager.item_paths(manager.library_name, item)
        replace_image(original, as_jpeg(source))
        overlay.unlink(missing_ok=True)
        write_metadata(manager.backup_manager, manager.library_name, item, source='kometa')
        return True
    except Exception:
        logger.exception('Could not use Kometa original %s', source)
        return False


def load_top_lists(manager, rating_sources, badge_style):
    """IMDb Top 250 and RT Certified Fresh / Verified Hot when Kometa's Top images are used."""
    from src.rating_overlay.multi_rating_badge import badge_variant
    style = badge_style or {}
    sources = rating_sources or {}
    if badge_variant(style) != 'kometa' or style.get('top_logos', style.get('imdb_top250_logo', True)) is False:
        return
    from src.rating_overlay.imdb_top250 import rt_top_ids, top250_ids
    try:
        if sources.get('imdb', True):
            manager.imdb_top250 = top250_ids()
        if sources.get('rt_critic', True) or sources.get('rt_audience', True):
            manager.rt_top = rt_top_ids()
    except Exception:
        logger.exception('Could not load the Top lists')


STEP_LABELS = {'capture_manual': 'manuelles Plex-Poster übernehmen', 'capture_current': 'aktuelles Plex-Poster übernehmen',
               'capture_if_missing': 'Original sichern', 'use_kometa_original': 'Kometa-Original verwenden',
               'reset_agent': 'Agent-Poster wählen'}


def preview_outcome(plan, manager, item, request, row, options):
    """(counter, reason) the real run would produce, without changing anything."""
    from src.rating_overlay.decision import plan_render
    from src.rating_overlay.poster_storage import paths
    if plan.skip:
        return plan.skip
    if plan.steps:
        return 'success', 'würde rendern: ' + ', '.join(STEP_LABELS.get(step, step) for step in plan.steps)
    inputs = manager.collect_inputs(item, request.badge_positions, request.badge_position or request.position)
    if inputs['problem']:
        return inputs['problem']
    original, _ = paths(manager.backup_manager, request.library_name, item)
    verdict, reason = plan_render(options, manager.backup_manager.has_overlay(request.library_name, item),
                                  row.get('render_hash'), manager.render_hash(inputs, original),
                                  False, plan.force_render)
    return ('success', f'würde rendern: {reason}') if verdict == 'render' else ('skipped', reason)


async def run_overlay(request):
    """Render overlays for a library or selected items; outcome is in ``progress``."""
    imdb_cache = api_cache = None
    try:
        progress.force_mode = request.force
        progress.begin_items('process', library=request.library_name)
        await publish()

        from src.rating_overlay.api_cache import ApiCache
        from src.rating_overlay.decision import Facts, Options, STEP_FAILURES, plan_item, plan_render
        from src.rating_overlay.kometa_conflicts import (
            ManualPosterQueue, has_overlay_label, has_kometizarr_overlay, remove_overlay_label)
        from src.rating_overlay.poster_storage import paths

        # Settings are read once per run, not once per item.
        settings = config.load_settings()
        auto_reset_kometa = (settings.get('kometa_conflicts') or {}).get('auto_reset', False)
        from src.rating_overlay.kometa_originals import find_original
        config.apply_saved_overlay_options(request, settings)
        api_cache = ApiCache()
        manager = config.create_manager(request.library_name, request.rating_sources,
                                        request.badge_style, request.media_overlay, api_cache=api_cache)
        manual_queue = ManualPosterQueue()
        current_overlay = request.operation == 'current_overlay'
        imdb_overlay = request.operation == 'imdb_overlay'
        use_current_plex = request.poster_source == 'current'
        options = Options(operation=request.operation, use_current_plex=use_current_plex,
                          force=request.force and not use_current_plex,
                          reset_kometa=request.reset_kometa, auto_reset_kometa=auto_reset_kometa,
                          lost_overlay=settings.get('lost_overlay', 'adopt'))

        if request.use_imdb_cache or (settings.get('imdb_direct') or {}).get('enabled'):
            from src.rating_overlay.imdb_cache import ImdbRatingCache
            imdb_cache = ImdbRatingCache()

        if request.rating_keys:
            all_items = config.selected_items(manager.library, request.rating_keys)
        elif request.rating_key:
            all_items = [manager.library.fetchItem(int(request.rating_key))]
        else:
            all_items = manager.library.all()
            if request.include_episodes and manager.library.type == 'show':
                all_items += manager.library.all(libtype='episode')
            if request.limit:
                all_items = all_items[:request.limit]

        if request.rating_key and all_items:
            try:
                await asyncio.to_thread(library_index.index_new_item, request.library_name, all_items[0])
            except Exception:
                logger.exception('Could not update library index for %s', request.rating_key)

        progress.total = len(all_items)
        if request.record_results:
            progress.results.update({str(key): 'gerendert' for key in request.completed_keys})
        if imdb_cache:
            imdb_ids = {manager._extract_imdb_id(getattr(item, 'guids', []) or []) for item in all_items}
            manager.imdb_ratings = imdb_cache.ratings(imdb_ids - {None})
        await asyncio.to_thread(load_top_lists, manager, request.rating_sources, request.badge_style)

        logger.info(f"🎬 Processing started: {request.library_name} ({len(all_items)} items)")

        summary = progress.extra.setdefault('summary', {}) if request.plan_only else {}

        def record(result):
            # Kept per item for the task list and the library browser; unchanged posters are only counted
            if request.record_results or not result.startswith('unverändert'):
                progress.results[str(item.ratingKey)] = result

        # Process each item
        for i, item in enumerate(all_items, 1):
            # Check if stop was requested
            if progress.stop_requested:
                logger.info(f"Stop requested - stopping processing at item {i}/{progress.total}")
                break

            progress.done = i
            progress.current = item.title
            if str(item.ratingKey) in request.completed_keys:
                progress.success += 1
                await publish()
                continue

            # 1. Facts → plan (pure, see decision.py) → 2. preparation steps
            kometa_label = has_overlay_label(item)
            # Kometa keeps an original for every poster it overlaid (only readable with /kometa mounted)
            kometa_original = find_original(settings, request.library_name, item.ratingKey) is not None
            row = item_row(request.library_name, item) or {}
            facts = Facts(
                kometa_label=kometa_label,
                recorded_conflict=imdb_overlay and conflicts.is_recorded(request.library_name, item),
                manual_state=manual_queue.state(request.library_name, item),
                has_overlay=has_kometizarr_overlay(manager.backup_manager, request.library_name, item),
                has_original=manager.backup_manager.has_backup(request.library_name, item),
                origin=row.get('original_source'),
                lost_overlay=overlay_lost(request.library_name, item, row),
                kometa_original=kometa_original,
                kometa_untagged=kometa_original and not kometa_label,
            )
            plan = plan_item(facts, options)
            if request.plan_only:
                counter, reason = preview_outcome(plan, manager, item, request, row, options)
                progress.count(counter, item.ratingKey, reason)
                summary[reason] = summary.get(reason, 0) + 1
                await publish()
                continue
            failed_step = None
            for step in plan.steps:
                if not run_preparation_step(step, manager, manual_queue, item):
                    failed_step = step
                    break
            skip = plan.skip or (STEP_FAILURES[failed_step] if failed_step else None)

            # 3. Inputs and render decision
            inputs = None
            if skip is None:
                if plan.origin:
                    record_poster_origin(request.library_name, item, plan.origin)
                inputs = manager.collect_inputs(item, request.badge_positions,
                                                request.badge_position or request.position)
                skip = inputs['problem']
            if skip is None:
                original, _ = paths(manager.backup_manager, request.library_name, item)
                new_hash = manager.render_hash(inputs, original)
                verdict, reason = plan_render(
                    options, manager.backup_manager.has_overlay(request.library_name, item),
                    row.get('render_hash'), new_hash, bool(plan.steps), plan.force_render)
                if verdict != 'render':
                    skip = ('skipped', reason)

            if skip is not None:
                counter, reason = skip
                if plan.steps:  # a captured original drops the old overlay file
                    library_index.set_flags(request.library_name, item.ratingKey,
                                            has_overlay=manager.backup_manager.has_overlay(request.library_name, item))
                if counter != 'skipped' or not reason.startswith('unverändert'):
                    mark_item(request.library_name, item, status=counter, reason=reason)
                if plan.remember_conflict:
                    await asyncio.to_thread(conflicts.remember, request.library_name, item)
                    if not request.plan_only:
                        progress.kometa_skipped(request.library_name, item.ratingKey)
                progress.count(counter, item.ratingKey)
                record(reason)
                await publish()
                continue

            # 4. Execute: the decision is made, so the manager renders unconditionally
            result = manager.process_movie(item, force=True, inputs=inputs)

            # Handle three-state return: True=success, None=skip, False=fail
            label_failed = False
            if result is None:
                progress.skipped += 1
            elif result:
                progress.success += 1
                original, _ = paths(manager.backup_manager, request.library_name, item)
                mark_item(request.library_name, item, status='rendered', reason=None,
                           rendered_at=time.time(), render_hash=manager.render_hash(inputs, original),
                           **uploaded_identity(item))
                library_index.invalidate_browse_poster(request.library_name, item.ratingKey)
                library_index.set_flags(request.library_name, item.ratingKey, has_overlay=True)
                library_index.cache_backup_artwork(request.library_name, item, manager.backup_manager, True)
                if kometa_label and not imdb_overlay:
                    try:
                        remove_overlay_label(item)
                    except Exception:
                        logger.exception('Could not remove Kometa Overlay label for %s', item.ratingKey)
                        label_failed = True
                if current_overlay and not label_failed:
                    manual_queue.remove(request.library_name, item)
                if (current_overlay or kometa_label or facts.kometa_untagged) and not label_failed:
                    conflicts.forget(request.library_name, item.ratingKey)
                if label_failed:
                    progress.count('failed', item.ratingKey)
                    progress.success -= 1
                    await asyncio.to_thread(conflicts.remember, request.library_name, item)
                if imdb_cache and not label_failed:
                    imdb_id = manager._extract_imdb_id(getattr(item, 'guids', []) or [])
                    if imdb_id in manager.imdb_ratings:
                        imdb_cache.mark_applied(request.library_name, item.ratingKey, imdb_id,
                                                manager.imdb_ratings[imdb_id])
            else:
                progress.count('failed', item.ratingKey)
                library_index.set_flags(request.library_name, item.ratingKey,
                                        has_overlay=manager.backup_manager.has_overlay(request.library_name, item))
                mark_item(request.library_name, item, status='failed',
                           reason=manager.last_problem or 'Rendern fehlgeschlagen')
            record('Kometa-Tag nicht entfernt' if label_failed else
                   'gerendert' if result is True else
                   (manager.last_problem or ('übersprungen' if result is None else 'fehlgeschlagen')))

            await publish()

            # Rate limiting
            await asyncio.sleep(0.3)

        config.log_summary(f"Processing Completed: {request.library_name}", progress.total,
                           {'Success': progress.success, 'Failed': progress.failed,
                            'Skipped': progress.skipped}, progress.items_started_at)

    except Exception as e:
        progress.error = str(e)
        logger.exception(f"❌ Processing failed: {request.library_name}")
    finally:
        progress.end_items()
        await publish(force=True)
        if imdb_cache:
            imdb_cache.close()
        if api_cache:
            api_cache.close()


def preview_posters(request):
    """Render overlays for a random sample; base64 images, no upload, no backup."""
    import random
    import base64
    import requests as req
    from src.rating_overlay.poster_storage import paths

    api_cache = None
    try:
        settings = config.load_settings()
        media_options = request.media_overlay or config.design_for(settings, request.library_name)['media_overlay'] or {}
        from src.rating_overlay.api_cache import ApiCache
        api_cache = ApiCache()
        manager = config.create_manager(request.library_name, request.rating_sources,
                                        request.badge_style, media_options, api_cache=api_cache)

        all_items = manager.library.all()
        if request.include_episodes and manager.library.type == 'show':
            all_items += manager.library.all(libtype='episode')
        sample = random.sample(all_items, min(request.count, len(all_items)))
        load_top_lists(manager, request.rating_sources, manager.badge_style)
        if (settings.get('imdb_direct') or {}).get('enabled'):
            from src.rating_overlay.imdb_cache import ImdbRatingCache
            cache = ImdbRatingCache()
            try:
                ids = {manager._extract_imdb_id(getattr(item, 'guids', []) or []) for item in sample}
                manager.imdb_ratings = cache.ratings(ids - {None})
            finally:
                cache.close()

        results = []
        for item in sample:
            try:
                inputs = manager.collect_inputs(item, request.badge_positions)
                if inputs['problem']:
                    continue

                # Use the clean original from the same backup layout the renderer uses
                original, _ = paths(manager.backup_manager, manager.library_name, item)
                poster_path = original if original.is_file() else None
                if not poster_path:
                    poster_url = manager.server.url(item.thumb) if item.type == 'episode' and item.thumb else item.posterUrl
                    if not poster_url:
                        continue
                    response = req.get(poster_url, headers={'X-Plex-Token': manager.plex_token}, timeout=15)
                    if response.status_code != 200:
                        continue
                    poster_path = Path(f'/tmp/kometizarr_prev_src_{item.ratingKey}.jpg')
                    poster_path.write_bytes(response.content)

                # Same renderer as the real run, without upload or backup
                output_path = Path(f'/tmp/kometizarr_prev_{item.ratingKey}.jpg')
                manager.render_image(poster_path, output_path, inputs)
                image_b64 = base64.b64encode(output_path.read_bytes()).decode()
                output_path.unlink(missing_ok=True)

                results.append({
                    'title': item.title,
                    'year': getattr(item, 'year', None),
                    'ratings': inputs['ratings'],
                    'image': image_b64,
                })

            except Exception as e:
                logger.warning(f"Preview skipped for {item.title}: {e}")
                continue

        return {'previews': results}

    except Exception as e:
        logger.error(f"Preview failed: {e}")
        return {'error': str(e), 'previews': []}
    finally:
        if api_cache:
            api_cache.close()


@tasks.handler('process')
async def process_task(task):
    from src.services.models import ProcessRequest
    completed = [key for key, result in (task['results'] or {}).items() if result == 'gerendert']
    await run_overlay(ProcessRequest(**{**task['payload'], 'completed_keys': completed,
                                        'record_results': True}))
    if progress.error:
        return progress.error
    return f'{progress.failed} Poster fehlgeschlagen' if progress.failed else None


@tasks.handler('batch')
async def batch_task(task):
    from src.services.models import ProcessRequest
    payload = task['payload']
    options = {key: value for key, value in payload.items() if key != 'library_names'}
    for name in payload['library_names']:
        progress.phase = name
        await run_overlay(ProcessRequest(library_name=name, **options))
        if progress.error or progress.failed:
            return f"{name}: {progress.error or str(progress.failed) + ' fehlgeschlagen'}"
    return None


@tasks.handler('webhook')
async def webhook_task(task):
    from src.services.models import ProcessRequest
    payload = task['payload']
    webhook = config.load_settings().get('webhook', {})
    if webhook.get('enabled') and (not webhook.get('libraries') or payload['library'] in webhook['libraries']):
        await run_overlay(ProcessRequest(library_name=payload['library'], rating_key=payload['key']))
    return progress.error


@tasks.handler('plan')
async def plan_task(task):
    from src.services.models import ProcessRequest
    progress.phase = 'Vorschau'
    await run_overlay(ProcessRequest(**{**task['payload'], 'plan_only': True, 'record_results': True}))
    return progress.error
