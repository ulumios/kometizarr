"""Plex webhook: queue new items for processing."""

import asyncio
import json
import logging

from fastapi import APIRouter, Form

from src.services import config, tasks

logger = logging.getLogger('kometizarr')
router = APIRouter()


@router.post("/webhook/plex")
async def plex_webhook(payload: str = Form(...)):
    """Receive Plex webhooks — triggers processing on library.new events."""
    try:
        data = json.loads(payload)
        event = data.get("event", "")
        logger.info(f"Plex webhook: {event}")

        if event == "library.new":
            webhook = config.load_settings().get("webhook", {})
            if not webhook.get("enabled"):
                return {"status": "ignored", "reason": "webhook disabled"}

            metadata = data.get("Metadata", {})
            target_library = metadata.get("librarySectionTitle")
            if not target_library:
                return {"status": "ignored", "reason": "could not determine library from event"}

            # If libraries list is non-empty, only process the listed libraries
            allowed = webhook.get("libraries", [])
            if allowed and target_library not in allowed:
                return {"status": "ignored", "reason": f"library {target_library!r} not in webhook scope"}

            rating_key = str(metadata.get("ratingKey", "")) or None
            item_title = metadata.get("title", "unknown")

            # Enqueue — worker processes items sequentially, no drops on bulk imports
            task_id = await tasks.enqueue('webhook', {'library': target_library, 'key': rating_key, 'title': item_title})
            queue_size = await asyncio.to_thread(tasks.with_tasks, 'queued_count')
            logger.info(f"Webhook queued: {target_library} / {item_title} (key={rating_key}, queue={queue_size})")
            return {"status": "queued", "library": target_library, "item": item_title, "queue_size": queue_size, "task_id": task_id}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return {"status": "ok"}
