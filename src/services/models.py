"""Request bodies shared by the API routes and the task runner."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProcessRequest(BaseModel):
    library_name: str
    position: str = "northwest"  # Legacy unified badge mode
    badge_position: Optional[Dict[str, float]] = None  # Legacy: free positioning for unified badge {x: %, y: %}
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None  # New: individual badge positions {'tmdb': {'x': 5, 'y': 5}, ...}
    force: bool = False
    limit: Optional[int] = None
    rating_sources: Optional[Dict[str, bool]] = None  # Which ratings to show
    badge_style: Optional[Dict[str, Any]] = None  # Badge styling options
    rating_key: Optional[str] = None  # If set, process only this specific Plex item
    rating_keys: Optional[List[str]] = None  # Selected Plex items, including seasons
    media_overlay: Optional[Dict[str, Any]] = None
    include_episodes: bool = False
    reset_to_plex: bool = False
    use_imdb_cache: bool = False
    record_results: bool = False
    reset_kometa: bool = False
    poster_source: Optional[str] = None
    operation: Optional[str] = None  # library UI: current_overlay, imdb_overlay, reset_plex
    completed_keys: List[str] = []
    plan_only: bool = False  # preview of a large run: decide, but change nothing
    recent_days: Optional[int] = None  # only items added or changed in Plex within these days


class ProcessBatchRequest(BaseModel):
    library_names: List[str]
    position: str = "northwest"
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    force: bool = False
    rating_sources: Optional[Dict[str, bool]] = None
    badge_style: Optional[Dict[str, Any]] = None
    media_overlay: Optional[Dict[str, Any]] = None
    include_episodes: bool = False
    recent_days: Optional[int] = None


class PreviewRequest(BaseModel):
    library_name: str
    badge_positions: Optional[Dict[str, Dict[str, float]]] = None
    rating_sources: Optional[Dict[str, bool]] = None
    badge_style: Optional[Dict[str, Any]] = None
    media_overlay: Optional[Dict[str, Any]] = None
    count: int = 3
    include_episodes: bool = False


class ConflictAction(BaseModel):
    library_name: str
    rating_keys: List[str]
    action: str


class SelectedImdbRequest(BaseModel):
    rating_keys: List[str]
    mode: str  # 'ratings' or 'both'
    reset_kometa: bool = False  # confirmed in the UI: take over Kometa posters first


class ImdbSyncRequest(BaseModel):
    mode: str = 'both'


class LibraryScanRequest(BaseModel):
    libraries: List[str]


class FreshPostersRequest(BaseModel):
    library_name: str
