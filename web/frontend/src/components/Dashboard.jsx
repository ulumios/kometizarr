import { useState, useEffect, useRef } from 'react'

function Dashboard({ onStartProcessing, onLibrarySelect }) {
  const [libraries, setLibraries] = useState([])
  const [selectedLibrary, setSelectedLibrary] = useState(null)   // for preview / restore
  const [selectedLibraries, setSelectedLibraries] = useState([]) // for processing (names)
  const [includeEpisodes, setIncludeEpisodes] = useState(false)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [position, setPosition] = useState('northwest')  // Keep for backward compat display
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
  const [force, setForce] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResults, setPreviewResults] = useState(null)  // null = closed, [] = loading/empty
  const [mediaOverlay, setMediaOverlay] = useState({ source: true, languages: true,
    source_position: { x: 30, y: 30 }, languages_position: { x: 30, y: 30 }, font_percent: 4, opacity: 180 })
  const [testImage, setTestImage] = useState(null)
  const [testRating, setTestRating] = useState('8.4')
  const [testSource, setTestSource] = useState('BluRay')
  const [testLanguages, setTestLanguages] = useState(['DE', 'EN'])
  const [testEpisode, setTestEpisode] = useState(true)
  const [testError, setTestError] = useState('')
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
      logo_size_multiplier: 1.0,  // Multiplier for logo within badge
      rating_color: '#FFFFFF',
      background_opacity: 215,
      font_family: 'Liberation Sans Bold'
    }
  })

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

  // Persist badge settings to server so webhook/cron use the same settings as the UI
  const persistBadgeSettings = async (patch) => {
    try {
      const res = await fetch('/api/settings')
      const current = await res.json()
      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, ...patch }),
      })
    } catch (e) {
      console.warn('Failed to persist badge settings to server:', e)
    }
  }

  useEffect(() => {
    fetchLibraries()
    // Sync badge settings between server and localStorage on mount.
    // Server is source of truth (webhook/cron read from it).
    // If server has settings, load them into component state.
    // If server is missing settings, push localStorage defaults.
    fetch('/api/settings')
      .then(r => r.json())
      .then(s => {
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

  useEffect(() => {
    if (selectedLibraries.length > 0) {
      fetchAggregatedStats(selectedLibraries)
    } else {
      setStats(null)
    }
  }, [selectedLibraries, includeEpisodes])

  const fetchLibraries = async () => {
    try {
      const res = await fetch('/api/libraries')
      const data = await res.json()
      if (data.libraries) {
        setLibraries(data.libraries)
        if (data.libraries.length > 0) {
          setSelectedLibrary(data.libraries[0])
          setSelectedLibraries(data.libraries.map(l => l.name)) // select all by default
        }
      }
    } catch (error) {
      console.error('Failed to fetch libraries:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchAggregatedStats = async (libraryNames) => {
    try {
      const results = await Promise.all(
        libraryNames.map(name =>
          fetch(`/api/library/${encodeURIComponent(name)}/stats?include_episodes=${includeEpisodes}`).then(r => r.json())
        )
      )
      const aggregated = results.reduce(
        (acc, data) => ({
          total_items: acc.total_items + (data.total_items || 0),
          processed_items: acc.processed_items + (data.processed_items || 0),
        }),
        { total_items: 0, processed_items: 0 }
      )
      aggregated.success_rate = aggregated.total_items > 0
        ? ((aggregated.processed_items / aggregated.total_items) * 100).toFixed(1)
        : '0.0'
      setStats(aggregated)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }

  const toggleLibrarySelection = (lib) => {
    const isDeselecting = selectedLibraries.includes(lib.name)
    const newSelected = isDeselecting
      ? selectedLibraries.filter(n => n !== lib.name)
      : [...selectedLibraries, lib.name]
    setSelectedLibraries(newSelected)
    // Update selectedLibrary for preview/restore: use clicked lib if selecting,
    // otherwise fall back to first remaining selected library
    if (!isDeselecting) {
      setSelectedLibrary(lib)
    } else if (newSelected.length > 0) {
      setSelectedLibrary(libraries.find(l => l.name === newSelected[0]))
    } else {
      setSelectedLibrary(null)
    }
    if (onLibrarySelect) onLibrarySelect(lib)
  }

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

  const handlePosterDrag = (e, badgeSource) => {
    if (!activeDragBadge && !badgeSource) return  // Not dragging

    const source = badgeSource || activeDragBadge
    if (!source || !ratingSources[source]) return  // Badge not enabled

    const rect = e.currentTarget.getBoundingClientRect()
    const clickX = e.clientX - rect.left
    const clickY = e.clientY - rect.top

    // Calculate position as percentage of poster dimensions (0-100)
    // Individual badges are small (~12% of poster width)
    const badgeWidthPercent = badgeStyle.individual_badge_size || 12
    const badgeHeightPercent = badgeWidthPercent * 1.4  // 1.4x aspect ratio

    // Center badge on cursor
    let xPercent = (clickX / rect.width) * 100 - (badgeWidthPercent / 2)
    let yPercent = (clickY / rect.height) * 100 - (badgeHeightPercent / 2)

    // Detect alignment with other badges (before clamping)
    const guides = []
    const threshold = 2  // Snap within 2%
    let alignedX = false
    let alignedY = false

    Object.keys(badgePositions).forEach(otherSource => {
      if (otherSource === source || !ratingSources[otherSource]) return

      const other = badgePositions[otherSource]
      const otherRight = other.x + badgeWidthPercent
      const otherBottom = other.y + badgeHeightPercent
      const otherCenterX = other.x + badgeWidthPercent / 2
      const otherCenterY = other.y + badgeHeightPercent / 2

      const dragRight = xPercent + badgeWidthPercent
      const dragBottom = yPercent + badgeHeightPercent
      const dragCenterX = xPercent + badgeWidthPercent / 2
      const dragCenterY = yPercent + badgeHeightPercent / 2

      // Check vertical alignments (X-axis) - only snap if not already aligned
      if (!alignedX) {
        if (Math.abs(xPercent - other.x) < threshold) {
          // Left edges align
          xPercent = other.x
          guides.push({ type: 'vertical', position: other.x })
          alignedX = true
        } else if (Math.abs(dragRight - otherRight) < threshold) {
          // Right edges align
          xPercent = otherRight - badgeWidthPercent
          guides.push({ type: 'vertical', position: otherRight })
          alignedX = true
        } else if (Math.abs(dragCenterX - otherCenterX) < threshold) {
          // Centers align
          xPercent = otherCenterX - badgeWidthPercent / 2
          guides.push({ type: 'vertical', position: otherCenterX })
          alignedX = true
        }
      }

      // Check horizontal alignments (Y-axis) - only snap if not already aligned
      if (!alignedY) {
        if (Math.abs(yPercent - other.y) < threshold) {
          // Top edges align
          yPercent = other.y
          guides.push({ type: 'horizontal', position: other.y })
          alignedY = true
        } else if (Math.abs(dragBottom - otherBottom) < threshold) {
          // Bottom edges align
          yPercent = otherBottom - badgeHeightPercent
          guides.push({ type: 'horizontal', position: otherBottom })
          alignedY = true
        } else if (Math.abs(dragCenterY - otherCenterY) < threshold) {
          // Centers align
          yPercent = otherCenterY - badgeHeightPercent / 2
          guides.push({ type: 'horizontal', position: otherCenterY })
          alignedY = true
        }
      }
    })

    // Clamp to edges AFTER alignment - simple 0-100% bounds (badges can overlap edges)
    xPercent = Math.max(0, Math.min(xPercent, 100))
    yPercent = Math.max(0, Math.min(yPercent, 100))

    setAlignmentGuides(guides)

    const newPosition = { x: Math.round(xPercent), y: Math.round(yPercent) }

    // Update only this badge's position
    const updated = { ...badgePositions, [source]: newPosition }
    setBadgePositions(updated)
    localStorage.setItem('kometizarr_badge_positions', JSON.stringify(updated))
  }

  const handleBadgeMouseDown = (e, badgeSource) => {
    e.stopPropagation()  // Prevent poster click
    setActiveDragBadge(badgeSource)
    // Don't move on initial click - only move when dragging (mousemove)
  }

  const handlePosterMouseMove = (e) => {
    if (activeDragBadge) {
      handlePosterDrag(e)
    }
  }

  const handleMouseUp = () => {
    if (activeDragBadge) {
      // Save final drag position to server (use ref to get latest state)
      persistBadgeSettings({ badge_positions: badgePositionsRef.current })
    }
    setActiveDragBadge(null)
    setAlignmentGuides([])  // Clear alignment guides
  }

  const startProcessing = async () => {
    if (selectedLibraries.length === 0) return

    const enabledBadgePositions = {}
    Object.keys(ratingSources).forEach(source => {
      if (ratingSources[source] && badgePositions[source]) {
        enabledBadgePositions[source] = badgePositions[source]
      }
    })

    const commonOptions = {
      position,
      badge_positions: enabledBadgePositions,
      force,
      rating_sources: ratingSources,
      badge_style: badgeStyle,
      media_overlay: mediaOverlay,
      include_episodes: includeEpisodes,
    }

    try {
      const isBatch = selectedLibraries.length > 1
      const res = await fetch(isBatch ? '/api/process-batch' : '/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          isBatch
            ? { library_names: selectedLibraries, ...commonOptions }
            : { library_name: selectedLibraries[0], ...commonOptions }
        ),
      })

      const data = await res.json()
      if (data.status === 'started') {
        onStartProcessing()
      }
    } catch (error) {
      console.error('Failed to start processing:', error)
    }
  }

  const restoreOriginals = async () => {
    if (!selectedLibrary) return

    if (!confirm(`Restore original ${includeEpisodes ? 'show and episode artwork' : 'posters'} in ${selectedLibrary.name}? This will remove their overlays.`)) {
      return
    }

    try {
      const res = await fetch('/api/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_name: selectedLibrary.name,
          include_episodes: includeEpisodes,
        }),
      })

      const data = await res.json()
      if (data.status === 'started') {
        onStartProcessing() // Use same callback to show progress view
      } else if (data.error) {
        alert(`Error: ${data.error}`)
      }
    } catch (error) {
      console.error('Failed to restore originals:', error)
      alert('Failed to restore originals')
    }
  }

  const previewPosters = async () => {
    if (!selectedLibrary) return
    setPreviewLoading(true)
    setPreviewResults([])

    const enabledBadgePositions = {}
    Object.keys(ratingSources).forEach(source => {
      if (ratingSources[source] && badgePositions[source]) {
        enabledBadgePositions[source] = badgePositions[source]
      }
    })

    try {
      const res = await fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_name: selectedLibrary.name,
          badge_positions: enabledBadgePositions,
          rating_sources: ratingSources,
          badge_style: badgeStyle,
          media_overlay: mediaOverlay,
          include_episodes: includeEpisodes,
          count: 3,
        }),
      })
      const data = await res.json()
      setPreviewResults(data.previews || [])
    } catch (error) {
      console.error('Preview failed:', error)
      setPreviewResults([])
    } finally {
      setPreviewLoading(false)
    }
  }

  const setMediaPosition = (key, axis, value) => {
    const next = { ...mediaOverlay, [key]: { ...mediaOverlay[key], [axis]: Number(value) } }
    setMediaOverlay(next)
    savePositionsSoon({ media_overlay: next })
  }

  const setEpisodeOption = (key, value) => {
    const next = { ...mediaOverlay, [key]: Number(value) }
    setMediaOverlay(next)
    savePositionsSoon({ media_overlay: next })
  }

  const previewTestImage = async () => {
    if (!testImage) return
    setPreviewLoading(true)
    setTestError('')
    const form = new FormData()
    form.append('image', testImage)
    form.append('options', JSON.stringify({ imdb: testRating, source: testSource,
      languages: testLanguages, badge_style: badgeStyle,
      imdb_position: badgePositions.imdb, media_overlay: mediaOverlay,
      episode: testEpisode }))
    try {
      const res = await fetch('/api/preview-test', { method: 'POST', body: form })
      const result = await res.json()
      if (!res.ok) throw new Error(result.detail || 'Preview failed')
      setPreviewResults([{ title: testImage.name, image: result.image, ratings: { imdb: testRating } }])
    } catch (error) {
      setTestError(error.message)
    } finally {
      setPreviewLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading libraries...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Library Selection */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Select Libraries</h2>
          {libraries.length > 1 && (
            <button
              onClick={() => {
                const allSelected = selectedLibraries.length === libraries.length
                setSelectedLibraries(allSelected ? [] : libraries.map(l => l.name))
                setSelectedLibrary(allSelected ? null : libraries[0])
              }}
              className="text-xs text-gray-400 hover:text-gray-200 transition"
            >
              {selectedLibraries.length === libraries.length ? 'Deselect all' : 'Select all'}
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {libraries.map((lib) => {
            const isSelected = selectedLibraries.includes(lib.name)
            return (
              <button
                key={lib.name}
                onClick={() => toggleLibrarySelection(lib)}
                className={`p-4 rounded-lg border-2 transition relative text-left ${
                  isSelected
                    ? 'border-blue-500 bg-blue-900/20'
                    : 'border-gray-700 hover:border-gray-600'
                }`}
              >
                {/* Checkbox indicator */}
                <div className={`absolute top-3 right-3 w-5 h-5 rounded border-2 flex items-center justify-center text-xs font-bold transition ${
                  isSelected ? 'border-blue-500 bg-blue-500 text-white' : 'border-gray-500'
                }`}>
                  {isSelected && '✓'}
                </div>
                <div className="font-semibold pr-7">{lib.name}</div>
                <div className="text-sm text-gray-400 mt-1">
                  {lib.type === 'movie' ? `🎬 ${lib.count} Filme` :
                    `📺 ${lib.count} Serien${includeEpisodes ? ` + ${lib.episode_count || 0} Episoden` : ''}`}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Library Stats */}
      {stats && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4">Library Statistics</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">Total Items</div>
              <div className="text-3xl font-bold mt-1">{stats.total_items}</div>
            </div>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">With Backups</div>
              <div className="text-3xl font-bold mt-1 text-green-400">
                {stats.processed_items}
              </div>
            </div>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="text-gray-400 text-sm">Backup Coverage</div>
              <div className="text-3xl font-bold mt-1 text-blue-400">
                {stats.success_rate}%
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Processing Options */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-4">Processing Options</h2>
        <fieldset className="bg-gray-900 rounded-lg p-4 mb-5 space-y-2">
          <legend className="text-sm font-medium px-1">Manueller Serienlauf</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="episode-scope" checked={!includeEpisodes}
              onChange={() => setIncludeEpisodes(false)} /> Nur Serienposter
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="episode-scope" checked={includeEpisodes}
              onChange={() => setIncludeEpisodes(true)} /> Serienposter und Episodenbilder
          </label>
          <p className="text-xs text-gray-400">Filmbibliotheken bleiben davon unberührt. Die Anzahl der Items und Backups wird passend zur Auswahl berechnet.</p>
        </fieldset>
        <div className="bg-gray-900 rounded-lg p-4 mb-5 space-y-3">
          <h3 className="text-sm font-medium">Episode badge layout</h3>
          <p className="text-xs text-gray-400">Relative edge spacing keeps badges in the same corner when episode artwork has different pixel dimensions.</p>
          {[
            ['IMDb badge size', 'episode_badge_percent', 5, 20, 1, 9, '% of image width'],
            ['Language label size', 'episode_font_percent', 1.5, 5, 0.1, 2.8, '% of image width'],
            ['Corner spacing', 'episode_edge_percent', 0, 6, 0.1, 1.2, '% from edges'],
          ].map(([label, key, min, max, step, fallback, unit]) => (
            <label key={key} className="flex gap-3 items-center text-xs text-gray-300">
              <span className="w-36">{label}</span>
              <input type="range" min={min} max={max} step={step}
                value={mediaOverlay[key] ?? fallback}
                onChange={e => setEpisodeOption(key, e.target.value)} className="flex-1 accent-blue-500" />
              <span className="w-32 text-right">{mediaOverlay[key] ?? fallback}{unit}</span>
            </label>
          ))}
          <label className="flex gap-3 items-center text-xs text-gray-300">
            <span className="w-36">EN flag</span>
            <select value={mediaOverlay.episode_english_flag ?? 'US'}
              onChange={e => {
                const next = { ...mediaOverlay, episode_english_flag: e.target.value }
                setMediaOverlay(next)
                savePositionsSoon({ media_overlay: next })
              }} className="bg-gray-800 border border-gray-700 rounded p-1">
              <option value="US">🇺🇸 US (reference)</option>
              <option value="GB">🇬🇧 GB</option>
            </select>
          </label>
        </div>
        <div className="bg-gray-900 rounded-lg p-4 mb-5 space-y-4">
          <h3 className="font-medium">Exact overlay positions</h3>
          <p className="text-xs text-gray-400">Pixel offsets on the original image. IMDb measures from top left; source from bottom left; languages from bottom right. Use the uploaded image below to verify the exact result.</p>
          {[
            ['IMDb', 'imdb'], ['TMDB', 'tmdb'], ['RT Critic', 'rt_critic'], ['RT Audience', 'rt_audience'],
            ['BluRay / PreRelease', 'source_position'],
            ['Episode languages', 'languages_position'],
          ].map(([label, key]) => (
            <div key={key} className="space-y-2 border-t border-gray-700 pt-3">
              <div className="text-sm text-white">{label}</div>
              {['x', 'y'].map(axis => {
                const ratingKey = ['imdb', 'tmdb', 'rt_critic', 'rt_audience'].includes(key)
                const value = ratingKey
                  ? badgePositions[key]?.[`${axis}_px`] ?? Math.round((badgePositions[key]?.[axis] ?? 2) * (axis === 'x' ? 10 : 14))
                  : mediaOverlay[key]?.[axis] ?? 30
                return <label key={axis} className="flex items-center gap-3 text-xs text-gray-400">
                  <span className="w-5 uppercase">{axis}</span>
                  <input type="range" min="0" max="2000" step="1" value={value}
                    onChange={e => {
                      if (ratingKey) {
                        const next = { ...badgePositions, [key]: { ...badgePositions[key], [`${axis}_px`]: Number(e.target.value) } }
                        setBadgePositions(next)
                        localStorage.setItem('kometizarr_badge_positions', JSON.stringify(next))
                        savePositionsSoon({ badge_positions: next })
                      } else setMediaPosition(key, axis, e.target.value)
                    }} className="flex-1 accent-blue-500" />
                  <input type="number" min="0" max="2000" value={value}
                    onChange={e => {
                      const n = Math.max(0, Math.min(2000, Number(e.target.value) || 0))
                      if (ratingKey) {
                        const next = { ...badgePositions, [key]: { ...badgePositions[key], [`${axis}_px`]: n } }
                        setBadgePositions(next)
                        savePositionsSoon({ badge_positions: next })
                      } else setMediaPosition(key, axis, n)
                    }} className="w-16 bg-gray-800 border border-gray-700 rounded px-1 py-1 text-white" />px
                </label>
              })}
            </div>
          ))}
          <div className="border-t border-gray-700 pt-3 space-y-3">
            <h3 className="text-sm font-medium">Test render with your own image</h3>
            <label className="flex gap-2 text-xs items-center">
              <input type="checkbox" checked={testEpisode} onChange={e => setTestEpisode(e.target.checked)} />
              Use episode sizing and corners
            </label>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setTestImage(e.target.files?.[0] || null)} className="text-xs w-full" />
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <label>IMDb <input type="number" min="0" max="10" step="0.1" value={testRating} onChange={e => setTestRating(e.target.value)} className="w-16 bg-gray-800 border border-gray-700 rounded p-1" /></label>
              <label>Source <select value={testSource} onChange={e => setTestSource(e.target.value)} className="bg-gray-800 border border-gray-700 rounded p-1">
                <option value="">None</option><option>BluRay</option><option>PreRelease</option>
              </select></label>
            </div>
            <div className="flex flex-wrap gap-3 text-xs">Audio languages:
              {['DE', 'EN', 'FR', 'ES', 'IT', 'JA'].map(code => <label key={code} className="flex gap-1 items-center">
                <input type="checkbox" checked={testLanguages.includes(code)} onChange={() => setTestLanguages(prev => prev.includes(code) ? prev.filter(x => x !== code) : [...prev, code])} />{code}
              </label>)}
            </div>
            <button disabled={!testImage || previewLoading} onClick={previewTestImage} className="px-3 py-2 bg-blue-600 disabled:bg-gray-700 rounded text-sm">Render test image</button>
            {testError && <p role="alert" className="text-red-400 text-xs">{testError}</p>}
          </div>
        </div>
        <div className="space-y-4">
          {/* Position & Styling - Side by Side Layout */}
          <div>
            <label className="block text-sm font-medium mb-2">Badge Positions & Styling</label>
            <div className="bg-gray-900 rounded-lg p-4">
              <div className="flex items-start gap-6">
                {/* LEFT: Draggable Poster Preview */}
                <div className="flex-shrink-0">
                  <svg
                    viewBox="0 0 120 168"
                    className="w-48 h-auto select-none"
                    onMouseMove={handlePosterMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                  >
                    {/* Poster Background */}
                    <rect x="0" y="0" width="120" height="168" fill="#1f2937" stroke="#4b5563" strokeWidth="2" rx="3" />

                    {/* Individual Badges - dynamically sized and styled */}
                    {(() => {
                      // Calculate badge dimensions based on style settings
                      const badgeSizePercent = includeEpisodes
                        ? (mediaOverlay.episode_badge_percent ?? 9)
                        : (badgeStyle.individual_badge_size || 9)
                      const badgeWidth = (badgeSizePercent / 100) * 120  // Scale to SVG viewBox
                      const badgeHeight = badgeWidth * 1.4  // 1.4 aspect ratio
                      const logoMultiplier = badgeStyle.logo_size_multiplier || 1.0
                      const fontMultiplier = badgeStyle.font_size_multiplier || 1.0
                      // Logo occupies top 60% of badge, scaled by logo_size_multiplier (max 2.0 → full area)
                      const logoAreaHeight = badgeHeight * 0.6 * Math.min(logoMultiplier / 2.0, 1.0)
                      // Font size applies to bottom 40% (rating number), scaled by font_size_multiplier
                      const fontSize = (badgeWidth / 14) * 8 * fontMultiplier
                      const opacity = (badgeStyle.background_opacity || 128) / 255

                      // Map font family to CSS font-family for SVG
                      const getFontFamily = (fontName) => {
                        if (fontName.includes('Mono')) return 'monospace'
                        if (fontName.includes('Serif')) return 'serif'
                        return 'sans-serif'
                      }

                      const getFontStyle = (fontName) => {
                        return fontName.includes('Oblique') || fontName.includes('Italic') ? 'italic' : 'normal'
                      }

                      const getFontWeight = (fontName) => {
                        return fontName.includes('Bold') ? 'bold' : 'normal'
                      }

                      const fontFamily = getFontFamily(badgeStyle.font_family || 'Liberation Sans Bold')
                      const fontStyle = getFontStyle(badgeStyle.font_family || 'DejaVu Sans Bold')
                      const fontWeight = getFontWeight(badgeStyle.font_family || 'DejaVu Sans Bold')

                      return (
                        <>
                          {ratingSources.tmdb && badgePositions.tmdb && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'tmdb')}
                            >
                              <rect x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120)} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1400 * 168 : badgePositions.tmdb.y / 100 * 168)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1400 * 168 : badgePositions.tmdb.y / 100 * 168) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#4a9eff" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1400 * 168 : badgePositions.tmdb.y / 100 * 168) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">T</text>
                            </g>
                          )}

                          {ratingSources.imdb && badgePositions.imdb && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'imdb')}
                              transform={`translate(${badgePositions.imdb.x_px != null ? badgePositions.imdb.x_px / 1000 * 120 : badgePositions.imdb.x / 100 * 120}, ${badgePositions.imdb.y_px != null ? badgePositions.imdb.y_px / 1400 * 168 : badgePositions.imdb.y / 100 * 168})`}
                            >
                              <rect width={badgeWidth} height={badgeWidth * 1.04} fill="#0f1116" fillOpacity={(badgeStyle.background_opacity ?? 215) / 255} rx="2" />
                              <rect x={badgeWidth * .05} y={badgeWidth * .08} width={badgeWidth * .90} height={badgeWidth * .42} fill="#f5c518" rx="1" />
                              <text x={badgeWidth / 2} y={badgeWidth * .29} fontSize={badgeWidth * .23} fill="#111" textAnchor="middle" dominantBaseline="middle" fontFamily="sans-serif" fontWeight="bold" className="pointer-events-none select-none">IMDb</text>
                              <text x={badgeWidth / 2} y={badgeWidth * .78} fontSize={badgeWidth * .31 * (badgeStyle.font_size_multiplier || 1)} fill={badgeStyle.rating_color || '#FFFFFF'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontWeight="bold" className="pointer-events-none select-none">8.4</text>
                            </g>
                          )}

                          {ratingSources.rt_critic && badgePositions.rt_critic && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_critic')}
                            >
                              <rect x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120)} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1400 * 168 : badgePositions.rt_critic.y / 100 * 168)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1400 * 168 : badgePositions.rt_critic.y / 100 * 168) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1400 * 168 : badgePositions.rt_critic.y / 100 * 168) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">C</text>
                            </g>
                          )}

                          {ratingSources.rt_audience && badgePositions.rt_audience && (
                            <g
                              className="cursor-move"
                              onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_audience')}
                            >
                              <rect x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120)} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1400 * 168 : badgePositions.rt_audience.y / 100 * 168)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                              <rect x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1400 * 168 : badgePositions.rt_audience.y / 100 * 168) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.25} rx="1" className="pointer-events-none" />
                              <text x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1400 * 168 : badgePositions.rt_audience.y / 100 * 168) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">A</text>
                            </g>
                          )}
                        </>
                      )
                    })()}

                    {mediaOverlay.source && <g>
                      <rect x={(mediaOverlay.source_position?.x ?? 30) / 1000 * 120}
                        y={168 - (mediaOverlay.source_position?.y ?? 30) / 1400 * 168 - 8}
                        width="30" height="8" rx="2" fill="#000" fillOpacity=".8" />
                      <text x={(mediaOverlay.source_position?.x ?? 30) / 1000 * 120 + 2}
                        y={168 - (mediaOverlay.source_position?.y ?? 30) / 1400 * 168 - 2}
                        fontSize="5" fill="white">{testSource || 'BluRay'}</text>
                    </g>}
                    {mediaOverlay.languages && <g>
                      <rect x={120 - (mediaOverlay.languages_position?.x ?? 30) / 1000 * 120 - 32}
                        y={168 - (mediaOverlay.languages_position?.y ?? 30) / 1400 * 168 - 8}
                        width="32" height="8" rx="2" fill="#000" fillOpacity=".8" />
                      <text x={120 - (mediaOverlay.languages_position?.x ?? 30) / 1000 * 120 - 30}
                        y={168 - (mediaOverlay.languages_position?.y ?? 30) / 1400 * 168 - 2}
                        fontSize="5" fill="white">🇩🇪 DE 🇬🇧 EN</text>
                    </g>}

                    {/* Alignment Guides */}
                    {alignmentGuides.map((guide, index) => {
                      if (guide.type === 'vertical') {
                        // Vertical line (for X-axis alignment)
                        const x = (guide.position / 100) * 120
                        return (
                          <line
                            key={`guide-${index}`}
                            x1={x}
                            y1={0}
                            x2={x}
                            y2={168}
                            stroke="#3b82f6"
                            strokeWidth="1"
                            strokeDasharray="4,4"
                            className="pointer-events-none"
                          />
                        )
                      } else {
                        // Horizontal line (for Y-axis alignment)
                        const y = (guide.position / 100) * 168
                        return (
                          <line
                            key={`guide-${index}`}
                            x1={0}
                            y1={y}
                            x2={120}
                            y2={y}
                            stroke="#3b82f6"
                            strokeWidth="1"
                            strokeDasharray="4,4"
                            className="pointer-events-none"
                          />
                        )
                      }
                    })}
                  </svg>
                  <div className="text-xs text-gray-500 mt-2 space-y-1">
                    <p className="font-medium">💡 Drag badges to position</p>
                    <div className="text-gray-400 leading-relaxed">
                      <span className="font-bold text-white">T</span>=<span className="font-bold">TMDB</span> • <span className="font-bold text-white">I</span>=<span className="font-bold">IMDb</span> • <span className="font-bold text-white">C</span>=<span className="font-bold">RT Critic</span> • <span className="font-bold text-white">A</span>=<span className="font-bold">RT Audience</span>
                    </div>
                  </div>
                </div>

                {/* RIGHT: Styling Controls */}
                <div className="flex-1 space-y-3">
                  {/* Badge Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Badge Size: {badgeStyle.individual_badge_size}% of image width
                    </label>
                    <input
                      type="range"
                      min="5"
                      max="30"
                      step="1"
                      value={badgeStyle.individual_badge_size}
                      onChange={(e) => updateBadgeStyle('individual_badge_size', parseInt(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Font Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Font Size: {badgeStyle.font_size_multiplier.toFixed(1)}x
                    </label>
                    <input
                      type="range"
                      min="0.5"
                      max="2.0"
                      step="0.1"
                      value={badgeStyle.font_size_multiplier}
                      onChange={(e) => updateBadgeStyle('font_size_multiplier', parseFloat(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Logo Size */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Logo Size: {(badgeStyle.logo_size_multiplier || 1.0).toFixed(1)}x
                    </label>
                    <input
                      type="range"
                      min="0.3"
                      max="2.0"
                      step="0.1"
                      value={badgeStyle.logo_size_multiplier || 1.0}
                      onChange={(e) => updateBadgeStyle('logo_size_multiplier', parseFloat(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Font and Color - Side by Side */}
                  <div className="grid grid-cols-2 gap-3">
                    {/* Font Family */}
                    <div>
                      <label className="text-xs text-gray-400 block mb-1">
                        Font
                      </label>
                      <select
                        value={badgeStyle.font_family}
                        onChange={(e) => updateBadgeStyle('font_family', e.target.value)}
                        className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                      >
                        <option value="Liberation Sans Bold">Arial-like Bold (reference)</option>
                        <option value="DejaVu Sans Bold">DejaVu Sans Bold</option>
                        <option value="DejaVu Sans">Sans Regular</option>
                        <option value="DejaVu Sans Bold Oblique">Sans Bold Italic</option>
                        <option value="DejaVu Sans Oblique">Sans Italic</option>
                        <option value="DejaVu Serif Bold">Serif Bold</option>
                        <option value="DejaVu Serif">Serif Regular</option>
                        <option value="DejaVu Serif Bold Italic">Serif Bold Italic</option>
                        <option value="DejaVu Serif Italic">Serif Italic</option>
                        <option value="DejaVu Sans Mono Bold">Mono Bold</option>
                        <option value="DejaVu Sans Mono">Mono Regular</option>
                        <option value="DejaVu Sans Mono Oblique">Mono Italic</option>
                      </select>
                    </div>

                    {/* Rating Color */}
                    <div>
                      <label className="text-xs text-gray-400 block mb-1">
                        Color
                      </label>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={badgeStyle.rating_color}
                          onChange={(e) => updateBadgeStyle('rating_color', e.target.value)}
                          className="w-10 h-8 rounded border border-gray-700 bg-gray-800 cursor-pointer"
                        />
                        <span className="text-xs text-gray-400 font-mono text-xs">{badgeStyle.rating_color}</span>
                      </div>
                    </div>
                  </div>

                  {/* Background Opacity */}
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">
                      Background: {Math.round((badgeStyle.background_opacity / 255) * 100)}%
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="255"
                      step="5"
                      value={badgeStyle.background_opacity}
                      onChange={(e) => updateBadgeStyle('background_opacity', parseInt(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  {/* Reset Button */}
                  <button
                    onClick={() => {
                      const defaults = {
                        individual_badge_size: 9,
                        font_size_multiplier: 1.0,
                        logo_size_multiplier: 1.0,
                        rating_color: '#FFFFFF',
                        background_opacity: 215,
                        font_family: 'Liberation Sans Bold'
                      }
                      setBadgeStyle(defaults)
                      localStorage.setItem('kometizarr_badge_style', JSON.stringify(defaults))
                      persistBadgeSettings({ badge_style: defaults })
                    }}
                    className="w-full text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition"
                  >
                    ↺ Apply reference defaults
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Force */}
          <div className="flex items-center">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              className="mr-3"
              id="force-checkbox"
            />
            <label htmlFor="force-checkbox" className="text-sm">
              Force reprocess (use when updating ratings or changing which sources to display)
            </label>
          </div>
          {force && (
            <div className="mt-2 p-3 bg-blue-900/20 border border-blue-700/50 rounded text-sm text-blue-300">
              ℹ️ Uses original posters from backup to apply fresh overlays with updated ratings. Original backups are never overwritten.
            </div>
          )}

          {/* Rating Sources */}
          <div>
            <label className="block text-sm font-medium mb-2">Rating Sources to Display</label>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.tmdb}
                  onChange={() => toggleRatingSource('tmdb')}
                  className="mr-2"
                  id="tmdb-checkbox"
                />
                <label htmlFor="tmdb-checkbox" className="text-sm">
                  🎬 TMDB (0-10 scale)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.imdb}
                  onChange={() => toggleRatingSource('imdb')}
                  className="mr-2"
                  id="imdb-checkbox"
                />
                <label htmlFor="imdb-checkbox" className="text-sm">
                  ⭐ IMDb (0-10 scale)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.rt_critic}
                  onChange={() => toggleRatingSource('rt_critic')}
                  className="mr-2"
                  id="rt-critic-checkbox"
                />
                <label htmlFor="rt-critic-checkbox" className="text-sm">
                  🍅 RT Critic (0-100%)
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={ratingSources.rt_audience}
                  onChange={() => toggleRatingSource('rt_audience')}
                  className="mr-2"
                  id="rt-audience-checkbox"
                />
                <label htmlFor="rt-audience-checkbox" className="text-sm">
                  🍿 RT Audience (0-100%)
                </label>
              </div>
            </div>
            {!Object.values(ratingSources).some(v => v) && (
              <div className="mt-2 p-3 bg-red-900/20 border border-red-700/50 rounded text-sm text-red-300">
                ⚠️ At least one rating source must be selected
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="grid grid-cols-3 gap-3">
            <button
              onClick={restoreOriginals}
              disabled={!selectedLibrary}
              className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              🔄 Restore
            </button>
            <button
              onClick={previewPosters}
              disabled={!selectedLibrary || previewLoading}
              className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              {previewLoading ? '⏳ Generating…' : '🔍 Preview'}
            </button>
            <button
              onClick={startProcessing}
              disabled={selectedLibraries.length === 0}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
            >
              {selectedLibraries.length > 1 ? `▶️ Process (${selectedLibraries.length})` : '▶️ Process'}
            </button>
          </div>
        </div>
      </div>
      <PreviewModal
        results={previewResults}
        loading={previewLoading}
        onClose={() => setPreviewResults(null)}
      />
    </div>
  )
}

// Preview Modal — rendered outside the main panel so it overlays everything
function PreviewModal({ results, loading, onClose }) {
  if (results === null) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={onClose}>
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-6 max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-white">🔍 Preview — 3 random items</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">✕</button>
        </div>

        {loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12">Fetching ratings & rendering posters…</div>
        )}

        {!loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12">No results — library may have no rated items with matching sources.</div>
        )}

        <div className="grid grid-cols-3 gap-5">
          {results.map((item, i) => (
            <div key={i} className="flex flex-col items-center gap-2">
              <img
                src={`data:image/jpeg;base64,${item.image}`}
                alt={item.title}
                className="rounded-lg w-full object-cover shadow-lg"
              />
              <div className="text-center">
                <div className="text-sm font-medium text-white truncate w-full">{item.title} {item.year && <span className="text-gray-400">({item.year})</span>}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {Object.entries(item.ratings).map(([k, v]) => `${k.toUpperCase()}: ${v}`).join(' · ')}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default Dashboard
