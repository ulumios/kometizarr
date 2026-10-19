"""Plex webhook: queue new items for processing."""

import asyncio
import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request

from src.services import config, health, tasks

logger = logging.getLogger('kometizarr')
router = APIRouter()


def _check_token(webhook, token, source):
    """Only enforced when a token is configured; works for Plex, Sonarr and Radarr URLs."""
    expected = webhook.get('token')
    if expected and not secrets.compare_digest(str(token or ''), str(expected)):
        health.record_webhook(source, 'abgelehnt', 'falsches oder fehlendes Token')
        raise HTTPException(403, 'Invalid webhook token')


@router.post("/webhook/plex")
async def plex_webhook(payload: str = Form(...), token: Optional[str] = None):
    """Receive Plex webhooks — triggers processing on library.new events."""
    _check_token(config.load_settings().get('webhook', {}), token, 'plex')
    try:
        data = json.loads(payload)
        event = data.get("event", "")
        logger.info(f"Plex webhook: {event}")
        metadata = data.get("Metadata", {})

        if event == "library.new":
            webhook = config.load_settings().get("webhook", {})
            if not webhook.get("enabled"):
                health.record_webhook('plex', event, 'ignoriert: ausgeschaltet', metadata.get("librarySectionTitle"), metadata.get("title"))
                return {"status": "ignored", "reason": "webhook disabled"}

            target_library = metadata.get("librarySectionTitle")
            if not target_library:
                return {"status": "ignored", "reason": "could not determine library from event"}

            # If libraries list is non-empty, only process the listed libraries
            allowed = webhook.get("libraries", [])
            if allowed and target_library not in allowed:
                health.record_webhook('plex', event, 'ignoriert: Bibliothek nicht ausgewählt', target_library, metadata.get("title"))
                return {"status": "ignored", "reason": f"library {target_library!r} not in webhook scope"}

            rating_key = str(metadata.get("ratingKey", "")) or None
            item_title = metadata.get("title", "unknown")

            # Enqueue — worker processes items sequentially, no drops on bulk imports
            task_id = await tasks.enqueue('webhook', {'library': target_library, 'key': rating_key, 'title': item_title})
            queue_size = await asyncio.to_thread(tasks.with_tasks, 'queued_count')
            logger.info(f"Webhook queued: {target_library} / {item_title} (key={rating_key}, queue={queue_size})")
            health.record_webhook('plex', event, f'eingereiht (#{task_id})', target_library, item_title)
            return {"status": "queued", "library": target_library, "item": item_title, "queue_size": queue_size, "task_id": task_id}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        health.record_webhook('plex', 'unlesbar', f'Fehler: {e}')
    return {"status": "ok"}


@router.post("/webhook/arr")
async def arr_webhook(request: Request, token: Optional[str] = None):
    """Sonarr/Radarr "On Import/Upgrade": render the title once Plex has scanned it."""
    from src.services import arr
    webhook = config.load_settings().get('webhook', {})
    _check_token(webhook, token, 'arr')
    data = await request.json()
    event = data.get('eventType', '')
    source = 'sonarr' if data.get('series') else 'radarr' if data.get('movie') else 'arr'
    if event == 'Test':
        health.record_webhook(source, event, 'Test empfangen')
        return {'status': 'ok', 'message': 'Kometizarr webhook reachable'}
    if not webhook.get('enabled'):
        health.record_webhook(source, event, 'ignoriert: ausgeschaltet')
        return {'status': 'ignored', 'reason': 'webhook disabled'}
    target = arr.parse(data)
    if target is None:
        health.record_webhook(source, event, 'ignoriert: kein Import')
        return {'status': 'ignored', 'reason': f'event {event!r} needs no render'}
    task_id = await tasks.enqueue('arr', {'target': target, 'attempt': 1}, delay=arr.FIRST_DELAY)
    health.record_webhook(source, event, f'eingereiht (#{task_id})', None, target['title'])
    logger.info(f"{source} webhook queued: {target['title']} (task {task_id})")
    return {'status': 'queued', 'task_id': task_id, 'title': target['title']}
