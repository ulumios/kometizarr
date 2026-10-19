"""
Kometizarr Web UI - FastAPI Backend

Only wiring lives here: routes in ``routes/``, logic in ``src/services/``.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add kometizarr to path
sys.path.insert(0, '/app/kometizarr')

from src.services import config, schedule, tasks  # noqa: E402
# Importing these registers their task handlers with the worker.
from src.services import conflicts, imdb, maintenance, overlay, restore  # noqa: E402,F401
from .routes import collections, conflicts as conflict_routes, imdb as imdb_routes  # noqa: E402
from .routes import health, library, maintenance as maintenance_routes, runs, settings, webhook  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

VERSION = "2.0.0-dev"


@asynccontextmanager
async def lifespan(_app):
    schedule.scheduler.start()
    try:
        from src.rating_overlay.item_state import ItemState
        with ItemState() as store:
            store.migrate(config.BACKUP_DIR / 'kometa_manual_pending.json')
    except Exception:
        logger.exception('Could not migrate Kometizarr state')
    schedule.reschedule(config.seed_defaults())
    worker = asyncio.create_task(tasks.worker())
    yield
    worker.cancel()
    schedule.scheduler.shutdown(wait=False)


app = FastAPI(title="Kometizarr API", version=VERSION, lifespan=lifespan)

# Kometizarr runs on the internal network only; the UI is served from another port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (runs, library, collections, settings, imdb_routes, conflict_routes, maintenance_routes,
               health, webhook):
    app.include_router(module.router)


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "app": "Kometizarr API", "version": VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
