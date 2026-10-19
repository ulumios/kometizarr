import { useState, useEffect, useRef } from 'react'

// Design state of the dashboard (badges, media labels, rating sources) and how it is
// saved: globally or as a library's own profile (see docs/KONZEPT.md, section 7).
export default function useDesignSettings() {
  const [badgePositions, setBadgePositions] = useState(() => {
    // Load from localStorage or set smart defaults (4 corners)
    const saved = localStorage.getItem('kometizarr_badge_positions')
    return saved ? JSON.parse(saved) : {
      tmdb: { x: 2, y: 2 },           // Top-left
      imdb: { x: 2, y: 2 },           // Top-left
      rt_critic: { x: 2, y: 78 },      // Bottom-left (78% down to fit ~20% badge + margin)
      rt_audience: { x: 70, y: 78 }    // Bottom-right
    }
  })
  const [activeDragBadge, setActiveDragBadge] = useState(null)  // Which badge is being dragged
  const [alignmentGuides, setAlignmentGuides] = useState([])  // Visual alignment guides
  const [mediaOverlay, setMediaOverlay] = useState({ source: true, languages: true, status: false,
    source_position: { x: 30, y: 30 }, languages_position: { x: 30, y: 30 }, status_position: { x: 30, y: 120 },
    source_labels: { bluray: 'BluRay', prerelease: 'PreRelease' },
    status_labels: { airing: 'Läuft gerade', running: 'Wird fortgesetzt', ended: 'Abgeschlossen', canceled: 'Abgesetzt' },
    label_size_percent: 4, episode_font_percent: 2.8 })
  const [ratingSources, setRatingSources] = useState(() => {
    // Load from localStorage or default to all enabled
    const saved = localStorage.getItem('kometizarr_rating_sources')
    return saved ? JSON.parse(saved) : {
      tmdb: false,
      imdb: true,
      rt_critic: false,
      rt_audience: false
    }
  })
  const [badgeStyle, setBadgeStyle] = useState(() => {
    // Load from localStorage or use defaults
    const saved = localStorage.getItem('kometizarr_badge_style')
    return saved ? JSON.parse(saved) : {
      individual_badge_size: 9,   // Individual badge size (% of poster width)
      font_size_multiplier: 1.0,  // Multiplier for font sizes
      logo_size_multiplier: 2.0,  // Existing visual size; displayed as 1.0x in the UI
      rating_color: '#FFFFFF',
      background_opacity: 215,
      font_family: 'Liberation Sans Bold'
    }
  })

  // '' = global design; a library name = that library's own design profile
  const [designScope, setDesignScope] = useState('')
  const [profiles, setProfiles] = useState({})
  const designScopeRef = useRef('')

  // Keep a ref so handleMouseUp can read latest badgePositions without stale closure
  const badgePositionsRef = useRef(badgePositions)
  const savePositionTimer = useRef(null)
  const pendingPositionPatch = useRef({})
  useEffect(() => { badgePositionsRef.current = badgePositions }, [badgePositions])
  useEffect(() => () => clearTimeout(savePositionTimer.current), [])

  const savePositionsSoon = (patch) => {
    pendingPositionPatch.current = { ...pendingPositionPatch.current, ...patch }
    clearTimeout(savePositionTimer.current)
    savePositionTimer.current = setTimeout(() => {
      const pending = pendingPositionPatch.current
      pendingPositionPatch.current = {}
      persistBadgeSettings(pending)
    }, 350)
  }

  // Persist badge settings to server so webhook/cron use the same settings as the UI.
  // With a library selected as design scope, the patch goes into that library's profile.
  const persistBadgeSettings = async (patch) => {
    try {
      const res = await fetch('/api/settings')
      const current = await res.json()
      const scope = designScopeRef.current
      const next = scope
        ? { ...current, library_profiles: { ...(current.library_profiles || {}),
            [scope]: { ...((current.library_profiles || {})[scope] || {}), ...patch } } }
        : { ...current, ...patch }
      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      })
      setProfiles(next.library_profiles || {})
    } catch (e) {
      console.warn('Failed to persist badge settings to server:', e)
    }
  }

  // Load the design that applies to a scope: the library profile on top of the global design.
  const changeDesignScope = async (scope, removeProfile = false) => {
    designScopeRef.current = scope
    setDesignScope(scope)
    const current = await fetch('/api/settings').then(r => r.json())
    if (removeProfile && scope) {
      const { [scope]: _removed, ...rest } = current.library_profiles || {}
      current.library_profiles = rest
      await fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(current) })
    }
    setProfiles(current.library_profiles || {})
    const design = { ...current, ...((current.library_profiles || {})[scope] || {}) }
    if (design.badge_positions) setBadgePositions(design.badge_positions)
    if (design.badge_style) setBadgeStyle(design.badge_style)
    if (design.rating_sources) setRatingSources(design.rating_sources)
    if (design.media_overlay) setMediaOverlay(m => ({ ...m, ...design.media_overlay }))
  }


  useEffect(() => {
    // Sync badge settings between server and localStorage on mount.
    // Server is source of truth (webhook/cron read from it).
    // If server has settings, load them into component state.
    // If server is missing settings, push localStorage defaults.
    fetch('/api/settings')
      .then(r => r.json())
      .then(s => {
        setProfiles(s.library_profiles || {})
        if (s.media_overlay) setMediaOverlay(current => ({ ...current, ...s.media_overlay }))
        if (s.badge_positions) {
          setBadgePositions(s.badge_positions)
          localStorage.setItem('kometizarr_badge_positions', JSON.stringify(s.badge_positions))
        }
        if (s.badge_style) {
          setBadgeStyle(s.badge_style)
          localStorage.setItem('kometizarr_badge_style', JSON.stringify(s.badge_style))
        }
        if (s.rating_sources) {
          setRatingSources(s.rating_sources)
          localStorage.setItem('kometizarr_rating_sources', JSON.stringify(s.rating_sources))
        }
        // Push localStorage defaults for anything the server doesn't have yet
        if (!s.badge_positions || !s.badge_style || !s.rating_sources) {
          persistBadgeSettings({
            badge_positions: s.badge_positions || badgePositions,
            badge_style: s.badge_style || badgeStyle,
            rating_sources: s.rating_sources || ratingSources,
          })
        }
      })
      .catch(() => {})
  }, [])

  const toggleRatingSource = (source) => {
    const updated = { ...ratingSources, [source]: !ratingSources[source] }
    setRatingSources(updated)
    localStorage.setItem('kometizarr_rating_sources', JSON.stringify(updated))
    persistBadgeSettings({ rating_sources: updated })
  }

  const updateBadgeStyle = (key, value) => {
    const updated = { ...badgeStyle, [key]: value }
    setBadgeStyle(updated)
    localStorage.setItem('kometizarr_badge_style', JSON.stringify(updated))
    persistBadgeSettings({ badge_style: updated })
  }

  const handlePosterDrag = (e, badgeSource, episodeCanvas = false) => {
    if (!activeDragBadge && !badgeSource) return  // Not dragging

    const source = badgeSource || activeDragBadge
    const mediaLabel = ['source_position', 'status_position', 'languages_position'].includes(source)
    if (!source || (!mediaLabel && !ratingSources[source])) return

    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const clickY = e.clientY - rect.top

    if (mediaLabel) {
      const width = episodeCanvas ? 1920 : 1000
      const height = episodeCanvas ? 1080 : 1500
      const sizePercent = episodeCanvas ? (mediaOverlay.episode_font_percent ?? 2.8)
        : (mediaOverlay.label_size_percent ?? mediaOverlay.font_percent ?? 4)
      const fontPx = width * sizePercent / 100 * (badgeStyle.font_size_multiplier ?? 1)
      const label = source === 'status_position' ? (mediaOverlay.status_labels?.ended ?? 'Abgeschlossen')
        : source === 'source_position' ? (mediaOverlay.source_labels?.bluray ?? 'BluRay') : 'DE EN'
      const labelWidth = source === 'languages_position' ? fontPx * 3.8 : fontPx * (label.length * .62 + .7)
      const labelHeight = source === 'languages_position' ? fontPx * 2.8 : fontPx * 1.6
      const x = source === 'languages_position'
        ? width - clickX / rect.width * width - labelWidth / 2
        : clickX / rect.width * width - labelWidth / 2
      const y = height - clickY / rect.height * height - labelHeight / 2
      // Set both coordinates in one update so a drag cannot overwrite its X value.
      const next = { ...mediaOverlay, [source]: {
        x: Math.round(Math.max(0, Math.min(width, x))),
        y: Math.round(Math.max(0, Math.min(height, y))) } }
      setMediaOverlay(next)
      savePositionsSoon({ media_overlay: next })
      return
    }

    const canvasWidth = episodeCanvas ? 1920 : 1000
    const canvasHeight = episodeCanvas ? 1080 : 1500
    const badgeWidth = (episodeCanvas ? mediaOverlay.episode_badge_percent ?? 9
      : badgeStyle.individual_badge_size || 9) / 100 * canvasWidth
    const badgeHeight = badgeWidth * (source === 'imdb' ? 1.04 : 1.4)
    const xPx = Math.round(Math.max(0, Math.min(canvasWidth - badgeWidth, clickX / rect.width * canvasWidth - badgeWidth / 2)))
    const yPx = Math.round(Math.max(0, Math.min(canvasHeight - badgeHeight, clickY / rect.height * canvasHeight - badgeHeight / 2)))
    setAlignmentGuides([])
    const newPosition = { x_px: xPx, y_px: yPx }

    // Update only this badge's position
    const updated = { ...badgePositions, [source]: newPosition }
    setBadgePositions(updated)
    badgePositionsRef.current = updated
    localStorage.setItem('kometizarr_badge_positions', JSON.stringify(updated))
  }

  const handleBadgeMouseDown = (e, badgeSource) => {
    e.stopPropagation()  // Prevent poster click
    setActiveDragBadge(badgeSource)
    // Don't move on initial click - only move when dragging (mousemove)
  }

  const handlePosterMouseMove = (e, episodeCanvas = false) => {
    if (activeDragBadge) {
      handlePosterDrag(e, null, episodeCanvas)
    }
  }

  const handleMouseUp = () => {
    if (activeDragBadge) {
      // Save final drag position to server (use ref to get latest state)
      if (!['source_position', 'status_position', 'languages_position'].includes(activeDragBadge)) {
        persistBadgeSettings({ badge_positions: badgePositionsRef.current })
      }
    }
    setActiveDragBadge(null)
    setAlignmentGuides([])  // Clear alignment guides
  }

  const setMediaPosition = (key, axis, value) => {
    const next = { ...mediaOverlay, [key]: { ...mediaOverlay[key], [axis]: Number(value) } }
    setMediaOverlay(next)
    savePositionsSoon({ media_overlay: next })
  }

  const toggleMediaOverlay = (key) => {
    const next = { ...mediaOverlay, [key]: !mediaOverlay[key] }
    setMediaOverlay(next)
    savePositionsSoon({ media_overlay: next })
  }

  const setEpisodeOption = (key, value) => {
    const next = { ...mediaOverlay, [key]: Number(value) }
    setMediaOverlay(next)
    savePositionsSoon({ media_overlay: next })
  }

  const setRatingPosition = (key, axis, value) => {
    const next = { ...badgePositions, [key]: { ...badgePositions[key], [`${axis}_px`]: Number(value) } }
    setBadgePositions(next)
    badgePositionsRef.current = next
    localStorage.setItem('kometizarr_badge_positions', JSON.stringify(next))
    savePositionsSoon({ badge_positions: next })
  }

  // Only the positions of enabled rating sources are sent to a run or preview.
  const enabledBadgePositions = () => Object.fromEntries(Object.keys(ratingSources)
    .filter(source => ratingSources[source] && badgePositions[source])
    .map(source => [source, badgePositions[source]]))

  return {
    badgePositions, activeDragBadge, alignmentGuides, mediaOverlay, setMediaOverlay, ratingSources,
    badgeStyle, setBadgeStyle, designScope, profiles, changeDesignScope, savePositionsSoon,
    persistBadgeSettings, toggleRatingSource, updateBadgeStyle, handleBadgeMouseDown,
    handlePosterMouseMove, handleMouseUp, setMediaPosition, toggleMediaOverlay, setEpisodeOption,
    setRatingPosition, enabledBadgePositions,
  }
}
