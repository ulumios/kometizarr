"""Collection management endpoints (decade, studio, keyword collections)."""

import logging
import os
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from src.collection_manager.manager import CollectionManager
from src.services import config

logger = logging.getLogger('kometizarr')
router = APIRouter()


# Collection Management Endpoints

@router.get("/api/collections")
async def get_collections(library_name: str):
    """Get all collections in a library - optimized for speed"""
    try:
        server = config.plex_server()
        library = server.library.section(library_name)

        collections = []
        # Use search() instead of collections() - much faster as it doesn't load full metadata
        for collection in library.search(libtype='collection'):
            collections.append({
                "title": collection.title,
                # Use childCount instead of len(items()) - avoids fetching all items
                "count": collection.childCount if hasattr(collection, 'childCount') else 0,
                "summary": collection.summary if hasattr(collection, 'summary') else ""
            })

        return {"collections": collections}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/collections/{collection_title}/items")
async def get_collection_items(collection_title: str, library_name: str):
    """Get first 10 items in a collection for preview"""
    try:
        server = config.plex_server()
        library = server.library.section(library_name)

        # Get the collection
        collection = library.collection(collection_title)

        # Get total count
        total_count = collection.childCount if hasattr(collection, 'childCount') else 0

        # Get just first 10 items for preview
        items = []
        limit = 10

        for i, item in enumerate(collection.items()):
            if i >= limit:
                break
            items.append({
                "title": item.title,
                "year": item.year if hasattr(item, 'year') else None,
                "rating": round(item.rating, 1) if hasattr(item, 'rating') and item.rating else None
            })

        return {
            "items": items,
            "total": total_count,
            "showing": len(items),
            "has_more": total_count > len(items)
        }
    except Exception as e:
        return {"error": str(e)}


class DecadeCollectionRequest(BaseModel):
    library_name: str
    decades: List[Dict]  # [{"title": "1980s Movies", "start": 1980, "end": 1989}, ...]


class StudioCollectionRequest(BaseModel):
    library_name: str
    studios: List[Dict]  # [{"title": "Marvel", "studios": ["Marvel Studios"]}, ...]


class KeywordCollectionRequest(BaseModel):
    library_name: str
    keywords: List[Dict]  # [{"title": "DC Universe", "keywords": ["dc comics", "batman"]}, ...]


@router.post("/api/collections/decade")
async def create_decade_collections(request: DecadeCollectionRequest):
    """Create decade collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            dry_run=False
        )

        collections = manager.create_decade_collections(request.decades)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/collections/studio")
async def create_studio_collections(request: StudioCollectionRequest):
    """Create studio collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            dry_run=False
        )

        collections = manager.create_studio_collections(request.studios)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/collections/keyword")
async def create_keyword_collections(request: KeywordCollectionRequest):
    """Create keyword collections"""
    try:
        manager = CollectionManager(
            plex_url=os.getenv('PLEX_URL'),
            plex_token=os.getenv('PLEX_TOKEN'),
            library_name=request.library_name,
            tmdb_api_key=os.getenv('TMDB_API_KEY'),
            dry_run=False
        )

        collections = manager.create_keyword_collections(request.keywords)

        return {
            "status": "success",
            "created": len(collections),
            "collections": [c.title for c in collections]
        }
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/collections/{collection_title}")
async def delete_collection(collection_title: str, library_name: str):
    """Delete a collection"""
    try:
        server = config.plex_server()
        library = server.library.section(library_name)

        # Get the collection
        collection = library.collection(collection_title)

        # Delete it
        collection.delete()

        return {"status": "success", "message": f"Deleted collection: {collection_title}"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/library/{library_name}/studios")
async def get_library_studios(library_name: str):
    """Get all unique studios/networks in a library (for debugging)"""
    try:
        server = config.plex_server()
        library = server.library.section(library_name)

        # Get all items
        all_items = library.all()

        # For TV shows, use 'network' field; for movies, use 'studio' field
        is_tv = library.type == 'show'
        field_name = 'network' if is_tv else 'studio'

        # Collect all unique studios/networks
        studios = {}
        for item in all_items:
            if is_tv:
                # TV shows - check network field
                if hasattr(item, 'network') and item.network:
                    value = item.network
                    if value not in studios:
                        studios[value] = 0
                    studios[value] += 1
            else:
                # Movies - check studio field
                if hasattr(item, 'studio') and item.studio:
                    value = item.studio
                    if value not in studios:
                        studios[value] = 0
                    studios[value] += 1

        # Sort by count descending
        sorted_studios = sorted(studios.items(), key=lambda x: x[1], reverse=True)

        return {
            "library": library_name,
            "field": field_name,
            "total_items": len(all_items),
            "studios": [{"name": name, "count": count} for name, count in sorted_studios]
        }
    except Exception as e:
        return {"error": str(e)}
