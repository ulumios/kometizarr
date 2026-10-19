"""What happens to one item during an overlay run, decided without touching Plex.

The run gathers facts, asks :func:`plan_item` which preparation steps are needed, executes
them, gathers the render inputs and finally asks :func:`plan_render` whether to upload.
The same functions drive the preview of large runs (see docs/KONZEPT.md, section 4).
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Preparation steps and the outcome when they fail: (counter, reason)
STEP_FAILURES = {
    'capture_manual': ('skipped', 'manuelles Plex-Poster konnte nicht gesichert werden'),
    'capture_current': ('failed', 'Plex-Poster konnte nicht gesichert werden'),
    'capture_if_missing': ('failed', 'Original-Backup fehlt'),
    'use_kometa_original': ('skipped', 'Kometa-Original nicht lesbar'),
    'reset_agent': ('skipped', 'kein sauberes Agent-Poster gefunden'),
}


@dataclass
class Options:
    operation: Optional[str] = None      # None, 'current_overlay', 'imdb_overlay'
    use_current_plex: bool = False
    force: bool = False
    reset_kometa: bool = False
    auto_reset_kometa: bool = False


@dataclass
class Facts:
    kometa_label: bool = False
    recorded_conflict: bool = False
    manual_state: str = 'none'           # 'none', 'waiting', 'changed'
    has_overlay: bool = False
    has_original: bool = False
    origin: Optional[str] = None
    kometa_original: bool = False        # Kometa's stored original is readable


@dataclass
class Plan:
    steps: List[str] = field(default_factory=list)
    skip: Optional[tuple] = None         # (counter, reason)
    remember_conflict: bool = False
    origin: Optional[str] = None         # original_source to record after the steps

    @classmethod
    def skipped(cls, counter, reason, remember_conflict=False):
        return cls(skip=(counter, reason), remember_conflict=remember_conflict)


def plan_item(facts: Facts, options: Options) -> Plan:
    current_overlay = options.operation == 'current_overlay'
    imdb_overlay = options.operation == 'imdb_overlay'
    plan = Plan()

    if imdb_overlay and (facts.kometa_label or facts.recorded_conflict):
        return Plan.skipped('skipped', 'Kometa-Konflikt: übersprungen', remember_conflict=True)
    has_overlay = facts.has_overlay
    if not current_overlay and facts.manual_state == 'waiting':
        return Plan.skipped('skipped', 'wartet auf manuelles Plex-Poster')
    if not current_overlay and facts.manual_state == 'changed':
        plan.steps.append('capture_manual')
        plan.origin = 'manual'
        has_overlay = False  # capturing a new original drops the old overlay

    if not current_overlay and facts.kometa_label:
        needs_reset = options.reset_kometa or (not has_overlay and options.auto_reset_kometa)
        if not has_overlay and not needs_reset:
            return Plan.skipped('skipped', 'Kometa-Konflikt: Reset erforderlich', remember_conflict=True)
        if needs_reset:
            # Kometa's own backup of the clean poster beats re-selecting the agent poster
            plan.steps.append('use_kometa_original' if facts.kometa_original else 'reset_agent')
            plan.origin = 'kometa' if facts.kometa_original else 'agent'

    if options.use_current_plex:
        plan.steps.append('capture_current')
        plan.origin = 'current_with_label' if facts.kometa_label else 'current'

    if imdb_overlay:
        if facts.origin == 'current_with_label':
            return Plan.skipped('skipped', 'Unsicheres Original: Kometa-Poster')
        if not facts.has_original:
            plan.steps.append('capture_if_missing')
            plan.origin = plan.origin or 'current'
        elif not facts.origin:
            plan.origin = 'existing_backup'
    return plan


def plan_render(options: Options, has_overlay: bool, stored_hash: Optional[str],
                new_hash: str, new_original: bool):
    """('render', reason) or ('skip', reason) / ('baseline', reason) for an evaluated item."""
    if options.operation or options.force:
        return 'render', 'erzwungen'
    if new_original:
        return 'render', 'neues Original'
    if not has_overlay:
        return 'render', 'neu'
    if stored_hash is None:
        # Rendered by an older version: adopt the current state instead of re-uploading everything
        return 'baseline', 'Ausgangszustand übernommen'
    if stored_hash == new_hash:
        return 'skip', 'unverändert'
    return 'render', 'Wertung oder Design geändert'
