"""
Poster Backup Manager - Safely backup and restore Plex posters

Inspired by Posterizarr's backup system
MIT License - Copyright (c) 2026 Kometizarr Contributors
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import requests
from PIL import Image

logger = logging.getLogger(__name__)


class PosterBackupManager:
    """Manage poster backups before applying overlays"""

    def __init__(self, backup_dir: str = '/backups'):
        """
        Initialize backup manager

        Args:
            backup_dir: Root directory for backups
        """
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Backup directory: {self.backup_dir}")

    # All locations come from poster_storage so every caller uses the ID layout.

    def item_paths(self, library_name: str, item):
        from .poster_storage import paths
        return paths(self, library_name, item)

    def has_backup(self, library_name: str, item) -> bool:
        return self.item_paths(library_name, item)[0].is_file()

    def has_overlay(self, library_name: str, item) -> bool:
        return self.item_paths(library_name, item)[1].is_file()

    def backup_poster(self, library_name: str, item, poster_url: str, plex_token: str,
                      metadata: Optional[Dict] = None) -> Optional[Path]:
        """Download the current Plex poster once; an existing original is never replaced here."""
        from .poster_storage import replace_image, write_metadata
        original, _ = self.item_paths(library_name, item)
        if original.is_file():
            return original
        try:
            response = requests.get(poster_url, headers={'X-Plex-Token': plex_token}, timeout=30)
            response.raise_for_status()
            replace_image(original, response.content)
            write_metadata(self, library_name, item, backed_up_at=datetime.now().isoformat(),
                           **(metadata or {}))
            logger.info(f"✓ Backed up: {original}")
            return original
        except Exception as e:
            logger.error(f"✗ Failed to backup poster for '{item.title}': {e}")
            return None

    def save_overlay_poster(self, library_name: str, item, overlay_image_path: str) -> Optional[Path]:
        _, overlay = self.item_paths(library_name, item)
        try:
            with Image.open(overlay_image_path) as img:
                img.convert('RGB').save(overlay, 'JPEG', quality=95)
            return overlay
        except Exception as e:
            logger.error(f"✗ Failed to save overlay for '{item.title}': {e}")
            return None

    def restore_original(self, library_name: str, item) -> bool:
        """Upload the original again and drop the rendered overlay."""
        original, overlay = self.item_paths(library_name, item)
        if not original.is_file():
            logger.warning(f"No backup found for '{item.title}'")
            return False
        try:
            item.uploadPoster(filepath=str(original))
            overlay.unlink(missing_ok=True)
            logger.info(f"✓ Restored original poster: {item.title}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to restore poster for '{item.title}': {e}")
            return False

    def list_backups(self, library_name: Optional[str] = None) -> list:
        """Every backup folder holding an original, including episode subfolders."""
        from .poster_storage import METADATA, ORIGINAL, OVERLAY
        roots = ([self.backup_dir / library_name] if library_name else
                 [d for d in self.backup_dir.iterdir() if d.is_dir()])
        backups = []
        for root in roots:
            if not root.is_dir():
                continue
            for original in sorted(root.rglob(ORIGINAL)):
                folder = original.parent
                metadata = None
                if (folder / METADATA).is_file():
                    try:
                        metadata = json.loads((folder / METADATA).read_text())
                    except ValueError:
                        pass
                backups.append({
                    'library': root.name,
                    'backup_id': str(folder.relative_to(root)),
                    'original_path': str(original),
                    'overlay_path': str(folder / OVERLAY) if (folder / OVERLAY).is_file() else None,
                    'metadata': metadata,
                })
        return backups
