"""Library listing, statistics, browsing index and poster proxy."""

import asyncio
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.services import config, library_index
from src.services.models import LibraryScanRequest

router = APIRouter()


@router.get('/api/library/{library_name}/browse')
async def browse_library(library_name: str, parent_key: Optional[int] = None, page: int = 1,
                         page_size: int = 60, q: str = '', episodes: bool = False,
                         refresh: bool = False, conflicts_only: bool = False, missing_overlay: bool = False):
    """Serve indexed Plex media; refresh asynchronously without blocking the UI."""
    try:
        updated_at, result = await asyncio.to_thread(
            library_index.read_library_index, library_name, parent_key, episodes, q, page, page_size, conflicts_only,
            missing_overlay)
        scan = library_index.scans.setdefault(library_name, {'is_running': False, 'error': None})
        if not scan['is_running'] and (refresh or (not updated_at and not scan['error'])):
            scan['is_running'] = True
            asyncio.create_task(library_index.run_library_index_scan(library_name))
        result.update(is_running=scan['is_running'], error=scan['error'], updated_at=updated_at)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/api/library/{library_name}/poster/{rating_key}')
async def browse_poster(library_name: str, rating_key: int):
    """Proxy a Plex poster without exposing the Plex token to the frontend."""
    from fastapi.responses import Response
    try:
        cache_key = (library_name, str(rating_key))
        cached = library_index.browse_image_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return Response(cached[1], media_type=cached[2], headers={'Cache-Control': 'private, max-age=60'})
        from src.rating_overlay.media_index import MediaIndex
        index = MediaIndex()
        try:
            thumb = index.thumb(library_name, rating_key)
            disk_image = index.cached_artwork(library_name, rating_key)
        finally:
            index.close()
        if disk_image:
            return Response(disk_image[0], media_type=disk_image[1],
                            headers={'Cache-Control': 'private, max-age=60'})
        server = None
        if not thumb or not thumb.startswith('/') or thumb.startswith('//'):
            server = config.plex_server()
            library = server.library.section(library_name)
            item = library.fetchItem(rating_key)
            if str(getattr(item, 'librarySectionID', library.key)) != str(library.key):
                raise HTTPException(404, 'Poster not found')
            thumb = getattr(item, 'thumb', None) or getattr(item, 'posterUrl', None)
            index = MediaIndex()
            try:
                index.update_thumb(library_name, rating_key, thumb)
            finally:
                index.close()
        if not thumb:
            raise HTTPException(404, 'Poster not found')
        from urllib.parse import urljoin
        poster_url = thumb if thumb.startswith(('http://', 'https://')) else (
            server.url(thumb) if server is not None else urljoin(os.getenv('PLEX_URL').rstrip('/') + '/', thumb.lstrip('/')))
        if server is None:
            import requests
            image = requests.get(poster_url, headers={'X-Plex-Token': os.getenv('PLEX_TOKEN')}, timeout=20)
        else:
            image = server._session.get(poster_url, headers={'X-Plex-Token': os.getenv('PLEX_TOKEN')}, timeout=20)
        image.raise_for_status()
        if not image.headers.get('Content-Type', '').startswith('image/'):
            raise HTTPException(502, 'Plex did not return an image')
        if len(library_index.browse_image_cache) >= 200:
            library_index.browse_image_cache.pop(next(iter(library_index.browse_image_cache)))
        library_index.browse_image_cache[cache_key] = (time.monotonic() + 180, image.content,
                                          image.headers.get('Content-Type', 'image/jpeg'))
        index = MediaIndex()
        try:
            index.store_artwork(library_name, rating_key, image.content,
                                image.headers.get('Content-Type', 'image/jpeg'), thumb)
        finally:
            index.close()
        return Response(image.content, media_type=image.headers.get('Content-Type', 'image/jpeg'),
                        headers={'Cache-Control': 'private, max-age=60'})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/libraries")
async def get_libraries():
    """Get all Plex libraries - optimized for speed"""
    try:
        if not os.getenv('PLEX_URL') or not os.getenv('PLEX_TOKEN'):
            return {"error": "PLEX_URL and PLEX_TOKEN must be configured"}

        server = config.plex_server()
        libraries = []

        for lib in server.library.sections():
            libraries.append({
                "name": lib.title,
                "type": lib.type,
                # Use totalSize instead of len(all()) - avoids fetching all items
                "count": lib.totalSize if hasattr(lib, 'totalSize') else 0,
                "episode_count": lib.totalViewSize(libtype='episode', includeCollections=False) if lib.type == 'show' else 0
            })

        return {"libraries": libraries}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/library/{library_name}/stats")
async def get_library_stats(library_name: str, include_episodes: bool = False):
    """Get statistics for a library"""
    try:
        library = config.plex_server().library.section(library_name)

        # Use totalSize for fast count instead of fetching all items
        show_or_movie_count = library.totalSize
        episode_count = library.totalViewSize(libtype='episode', includeCollections=False) if library.type == 'show' and include_episodes else 0
        total = show_or_movie_count + episode_count

        # Count rendered overlays in the same layout poster_storage.paths() writes
        backup_dir = config.backup_library_dir(library_name)
        processed = 0
        if backup_dir.is_dir():
            # ID layout first, then folders not yet migrated from the title layout
            processed = sum(1 for _ in backup_dir.glob('*/overlay.jpg'))
            processed += sum(1 for _ in backup_dir.glob('*/poster_overlay.jpg'))
            if episode_count:
                processed += sum(1 for _ in backup_dir.glob('*/S*E*/overlay.jpg'))
                processed += sum(1 for _ in backup_dir.glob('*/S*E*-poster_overlay.jpg'))
                processed += sum(1 for _ in backup_dir.glob('episodes/*/overlay.jpg'))

        success_rate = (processed / total * 100) if total > 0 else 0

        return {
            "library_name": library_name,
            "total_items": total,
            "processed_items": processed,
            "success_rate": round(success_rate, 1)
        }
    except Exception as e:
        return {"error": str(e)}


@router.get('/api/library-scan/status')
async def library_scan_status():
    return {'scans': library_index.scans}


@router.post('/api/library-scan')
async def start_library_scan(request: LibraryScanRequest):
    if not request.libraries:
        raise HTTPException(400, 'Select at least one library')
    available = {section.title for section in config.plex_server().library.sections()}
    unknown = [name for name in request.libraries if name not in available]
    if unknown:
        raise HTTPException(404, f'Unknown library: {unknown[0]}')
    started = [name for name in request.libraries if library_index.start_scan(name)]
    return {'status': 'started', 'libraries': started}
