"""Status page."""

import asyncio

from fastapi import APIRouter

from src.services import health

router = APIRouter()


@router.get('/api/health')
async def get_health(refresh: bool = False):
    """Plex, API keys, IMDb dataset, disk, mounts, queue, schedule and recent webhooks."""
    return await asyncio.to_thread(health.report, refresh)
