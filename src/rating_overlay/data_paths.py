"""Default locations of Kometizarr's data files (override with KOMETIZARR_BACKUP_DIR)."""

import os
from pathlib import Path


def data_file(name):
    return Path(os.getenv('KOMETIZARR_BACKUP_DIR', '/backups')) / name
