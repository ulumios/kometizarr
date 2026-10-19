import { useState, useEffect } from 'react'
import useDesignSettings from './dashboard/useDesignSettings'
import LibrarySelection from './dashboard/LibrarySelection'
import LibraryStats from './dashboard/LibraryStats'
import DesignScope from './dashboard/DesignScope'
import BadgeEditor from './dashboard/BadgeEditor'
import RatingSources from './dashboard/RatingSources'
import ActionButtons from './dashboard/ActionButtons'
import PreviewModal from './dashboard/PreviewModal'

function Dashboard({ onStartProcessing, onLibrarySelect, onOpenTasks }) {
  const [libraries, setLibraries] = useState([])
  const [selectedLibrary, setSelectedLibrary] = useState(null)   // for preview / restore
  const [selectedLibraries, setSelectedLibraries] = useState([]) // for processing (names)
  const [includeEpisodes, setIncludeEpisodes] = useState(false)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [position, setPosition] = useState('northwest')  // Keep for backward compat display
  const [force, setForce] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResults, setPreviewResults] = useState(null)  // null = closed, [] = loading/empty
  const design = useDesignSettings()
  const { ratingSources, badgeStyle, mediaOverlay } = design

  useEffect(() => { fetchLibraries() }, [])

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

  // Preview of a large run: same decisions as the real run, nothing is changed.
  const planProcessing = async () => {
    if (selectedLibraries.length !== 1) return
    const res = await fetch('/api/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ library_name: selectedLibraries[0], force, include_episodes: includeEpisodes }),
    })
    if (res.ok) onOpenTasks?.()
  }

  const startProcessing = async () => {
    if (selectedLibraries.length === 0) return

    const enabledBadgePositions = design.enabledBadgePositions()

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

    const enabledBadgePositions = design.enabledBadgePositions()

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading libraries...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <LibrarySelection libraries={libraries} selectedLibraries={selectedLibraries}
        setSelectedLibraries={setSelectedLibraries} setSelectedLibrary={setSelectedLibrary}
        toggleLibrarySelection={toggleLibrarySelection} includeEpisodes={includeEpisodes} />

      <LibraryStats stats={stats} />

      {/* Processing Options */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-4">Processing Options</h2>
        <DesignScope libraries={libraries} design={design} />
        <div className="bg-gray-900 rounded-lg p-4 mb-5 space-y-2">
          <div className="text-sm font-medium">Manueller Serienlauf</div>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="episode-scope" checked={!includeEpisodes}
              onChange={() => setIncludeEpisodes(false)} /> Nur Serienposter
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="episode-scope" checked={includeEpisodes}
              onChange={() => setIncludeEpisodes(true)} /> Serienposter und Episodenbilder
          </label>
          <p className="text-xs text-gray-400">Filmbibliotheken bleiben davon unberührt. Die Anzahl der Items und Backups wird passend zur Auswahl berechnet.</p>
        </div>
        <div className="space-y-4">
          <BadgeEditor design={design} includeEpisodes={includeEpisodes} />

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

          <RatingSources design={design} />

          <ActionButtons selectedLibrary={selectedLibrary} selectedLibraries={selectedLibraries}
            previewLoading={previewLoading} restoreOriginals={restoreOriginals} previewPosters={previewPosters}
            planProcessing={planProcessing} startProcessing={startProcessing} />
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

export default Dashboard
