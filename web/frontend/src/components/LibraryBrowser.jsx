import { useEffect, useState } from 'react'

const saved = (() => { try { return JSON.parse(sessionStorage.getItem('kometizarr-browser') || '{}') } catch { return {} } })()

export default function LibraryBrowser({ onStartProcessing }) {
  const [libraries, setLibraries] = useState([])
  const [library, setLibrary] = useState(saved.library || '')
  const [parent, setParent] = useState(saved.parent || null)
  const [trail, setTrail] = useState(saved.trail || [])
  const [page, setPage] = useState(saved.page || 1)
  const [search, setSearch] = useState(saved.search || '')
  const [query, setQuery] = useState('')
  const [searchEpisodes, setSearchEpisodes] = useState(saved.searchEpisodes || false)
  const [conflictsOnly, setConflictsOnly] = useState(saved.conflictsOnly || false)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState([])
  const [loading, setLoading] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const [busy, setBusy] = useState(false)
  const [posterVersion, setPosterVersion] = useState(() => Date.now())
  const [posterVersions, setPosterVersions] = useState({})
  const [pendingJob, setPendingJob] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem('kometizarr-browser-job') || 'null') } catch { return null }
  })
  const [imdbJob, setImdbJob] = useState(null)

  useEffect(() => {
    sessionStorage.setItem('kometizarr-browser', JSON.stringify({
      library, parent, trail, page, search, searchEpisodes, conflictsOnly,
    }))
  }, [library, parent, trail, page, search, searchEpisodes, conflictsOnly])

  useEffect(() => {
    if (!pendingJob) return undefined
    const poll = () => fetch(`/api/tasks/${pendingJob.id}/status`).then(r => r.json()).then(task => {
      if (!['completed', 'failed'].includes(task.status)) return
      const version = Date.now()
      setPosterVersions(previous => Object.fromEntries([
        ...Object.entries(previous), ...pendingJob.keys.map(key => [String(key), version]),
      ]))
      setReload(value => value + 1)
      setPendingJob(null)
      sessionStorage.removeItem('kometizarr-browser-job')
    }).catch(() => {})
    poll()
    const timer = setInterval(poll, 2000)
    return () => clearInterval(timer)
  }, [pendingJob])

  useEffect(() => {
    const timer = setTimeout(() => { setQuery(search.trim()); setPage(1) }, 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    fetch('/api/imdb-sync/status').then(r => r.json()).then(data => {
      if (data.library === library) setImdbJob(data)
    }).catch(() => {})
  }, [library])

  useEffect(() => {
    const timer = setInterval(() => fetch('/api/imdb-sync/status').then(r => r.json()).then(data => {
      if (data.library === library) setImdbJob(data)
    }).catch(() => {}), 1500)
    return () => clearInterval(timer)
  }, [library])

  useEffect(() => {
    if (imdbJob?.phase === 'Abgeschlossen' && !imdbJob.is_running && imdbJob.rendered > 0) {
      setPosterVersion(Date.now())
    }
  }, [imdbJob?.is_running, imdbJob?.phase])

  useEffect(() => {
    fetch('/api/libraries').then(r => r.json()).then(data => {
      const available = (data.libraries || []).filter(lib => ['movie', 'show'].includes(lib.type))
      setLibraries(available)
      setLibrary(current => current || available[0]?.name || '')
    }).catch(e => setError(e.message))
  }, [])

  useEffect(() => {
    if (!library) return
    let active = true
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ page: String(page) })
    if (parent) params.set('parent_key', parent.key)
    if (query) params.set('q', query)
    if (searchEpisodes && !parent) params.set('episodes', 'true')
    if (conflictsOnly) params.set('conflicts_only', 'true')
    fetch(`/api/library/${encodeURIComponent(library)}/browse?${params}`)
      .then(async r => { const data = await r.json(); if (!r.ok) throw Error(data.detail || 'Library unavailable'); return data })
      .then(data => { if (active) { setItems(data.items); setTotal(data.total); setIndexing(!!data.is_running); if (data.error) setError(data.error) } })
      .catch(e => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [library, parent, page, query, searchEpisodes, conflictsOnly, reload])

  useEffect(() => {
    if (!indexing) return
    const timer = setTimeout(() => setReload(value => value + 1), 2500)
    return () => clearTimeout(timer)
  }, [indexing, reload])

  const switchLibrary = name => { setLibrary(name); setParent(null); setTrail([]); setSearch(''); setSearchEpisodes(false); setPage(1); setSelected([]); setImdbJob(null) }
  const openFolder = item => { setTrail(previous => [...previous, parent]); setParent(item); setSearch(''); setPage(1); setSelected([]) }
  const goBack = () => { setParent(trail.at(-1) || null); setTrail(previous => previous.slice(0, -1)); setSearch(''); setPage(1); setSelected([]) }
  const toggle = key => setSelected(previous => previous.includes(key) ? previous.filter(k => k !== key) : [...previous, key])
  const allVisible = items.length > 0 && items.every(item => selected.includes(item.key))
  const episodeView = parent?.type === 'season' || (searchEpisodes && items.some(item => item.type === 'episode'))
  const launch = async reset => {
    if (!selected.length || busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(reset ? '/api/restore' : '/api/process', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ library_name: library, rating_keys: selected, force: false,
          operation: reset ? 'reset_plex' : 'current_overlay',
          poster_source: reset ? null : 'current', reset_to_plex: reset }),
      })
      const data = await response.json()
      if (!response.ok || data.error || data.status !== 'started') throw Error(data.error || data.detail || 'Could not start')
      setConfirmReset(false)
      const job = { id: data.task_id, keys: [...selected] }
      sessionStorage.setItem('kometizarr-browser-job', JSON.stringify(job))
      setPendingJob(job)
      onStartProcessing()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  const launchImdb = async mode => {
    if (!selected.length || busy || imdbJob?.is_running) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`/api/library/${encodeURIComponent(library)}/selected-imdb`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating_keys: selected, mode }),
      })
      const data = await response.json()
      if (!response.ok) throw Error(data.detail || 'IMDb-Lauf konnte nicht gestartet werden')
      const job = { id: data.task_id, keys: [...selected] }
      sessionStorage.setItem('kometizarr-browser-job', JSON.stringify(job))
      setPendingJob(job)
      setImdbJob({ is_running: false, phase: `Aufgabe #${data.task_id} wartet`, library, logs: [] })
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return <section className="space-y-5 text-gray-200">
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <h2 className="font-semibold text-lg mb-2">Bibliotheken durchsuchen</h2>
      <p className="text-sm text-gray-400 mb-4">Eine Serie wählt ihr Hauptposter. Öffne sie, um einzelne Staffeln auszuwählen; eine Staffel bearbeitet ihre Episodenbilder.</p>
      <div className="flex flex-wrap gap-2">{libraries.map(lib => <button key={lib.name} onClick={() => switchLibrary(lib.name)}
        className={`px-3 py-2 rounded border ${library === lib.name ? 'bg-blue-700 border-blue-500' : 'bg-gray-900 border-gray-600 hover:border-gray-400'}`}>{lib.name}</button>)}</div>
      {parent && <button className="text-blue-300 mt-4 hover:underline" onClick={goBack}>← {library} / {parent.title}</button>}
      <div className="mt-4 flex flex-wrap gap-3 items-center">
        <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Titel, Serie, Staffel oder Jahr suchen…"
          aria-label="Bibliothek durchsuchen" className="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm flex-1 min-w-52" />
        {!parent && libraries.find(lib => lib.name === library)?.type === 'show' && <label className="text-sm flex items-center gap-2">
          <input type="checkbox" checked={searchEpisodes} onChange={e => { setSearchEpisodes(e.target.checked); setPage(1); setSelected([]) }} /> Episoden anzeigen
        </label>}
      </div>
      {indexing && <p className="text-sm text-blue-300 mt-2">Bibliothek wird im Hintergrund indexiert…</p>}
    </div>
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <div className="flex flex-wrap gap-3 justify-between items-center mb-4">
        <span>{loading ? 'Lade Einträge…' : `${total} ${conflictsOnly ? 'Konflikte' : parent?.type === 'show' ? 'Staffeln' : parent?.type === 'season' || searchEpisodes ? 'Episoden' : 'Einträge'}`}</span>
        <div className="flex gap-3 items-center"><label className="text-sm flex items-center gap-2"><input type="checkbox" checked={conflictsOnly} onChange={e => { setConflictsOnly(e.target.checked); setPage(1); setSelected([]) }} /> Nur Konflikte</label>
        <button disabled={!items.length} onClick={() => setSelected(previous => allVisible ? previous.filter(k => !items.some(item => item.key === k)) : [...new Set([...previous, ...items.map(item => item.key)])])}
          className="text-sm text-blue-300 disabled:text-gray-600">{allVisible ? 'Sichtbare abwählen' : 'Sichtbare auswählen'}</button></div>
      </div>
      <div className={`grid grid-cols-2 sm:grid-cols-3 gap-4 ${episodeView ? 'lg:grid-cols-3 xl:grid-cols-4' : 'lg:grid-cols-5 xl:grid-cols-6'}`}>{items.map(item => <div key={item.key} className={`rounded-lg border overflow-hidden ${selected.includes(item.key) ? 'border-blue-500 bg-blue-950/30' : 'border-gray-600 bg-gray-900'}`}>
        <button type="button" onClick={() => toggle(item.key)} aria-label={`${item.title} auswählen`} className={`relative block w-full bg-gray-950 ${item.type === 'episode' ? 'aspect-video' : 'aspect-[2/3]'}`}>
          <span className="absolute inset-0 flex items-center justify-center text-xs text-gray-500 p-3">Kein Poster verfügbar</span>
          <img loading="lazy" src={`/api/library/${encodeURIComponent(library)}/poster/${encodeURIComponent(item.key)}?v=${posterVersions[String(item.key)] || posterVersion}`} alt="" className="absolute inset-0 w-full h-full object-cover" onLoad={event => { event.currentTarget.style.display = '' }} onError={event => { event.currentTarget.style.display = 'none' }} />
          <span className={`absolute top-2 right-2 rounded px-2 py-1 text-sm ${selected.includes(item.key) ? 'bg-blue-600 text-white' : 'bg-gray-900/90 text-gray-200'}`}>{selected.includes(item.key) ? '✓' : '○'}</span>
        </button>
        <div className="p-2.5"><div className="text-sm truncate" title={item.title}>{item.type === 'season' ? `Staffel ${item.index ?? '–'} · ` : item.type === 'episode' ? `${item.series ? `${item.series} · ` : ''}S${String(item.season ?? 0).padStart(2, '0')}E${String(item.index ?? 0).padStart(2, '0')} · ` : ''}{item.title} {item.year ? `(${item.year})` : ''}</div>
        {['show', 'season'].includes(item.type) && <button className="text-blue-300 text-xs mt-1" onClick={() => openFolder(item)}>{item.type === 'show' ? 'Staffeln anzeigen' : 'Episoden anzeigen'} →</button>}</div>
      </div>)}</div>
      {total > 60 && <div className="flex items-center gap-4 mt-5"><button disabled={page === 1} onClick={() => setPage(page - 1)}>← Zurück</button><span>Seite {page} / {Math.ceil(total / 60)}</span><button disabled={page * 60 >= total} onClick={() => setPage(page + 1)}>Weiter →</button></div>}
    </div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 flex flex-wrap items-center gap-3">
      <span className="text-sm mr-auto">{selected.length} ausgewählt</span>
      <button disabled={!selected.length || busy || imdbJob?.is_running} onClick={() => launch(false)} className="px-4 py-2 rounded bg-blue-600 disabled:opacity-40">Nur Overlay</button>
      <button disabled={!selected.length || busy || imdbJob?.is_running} onClick={() => launchImdb('both')} className="px-4 py-2 rounded bg-emerald-700 disabled:opacity-40">Overlay mit aktueller IMDb</button>
      <button disabled={!selected.length || busy} onClick={() => setConfirmReset(true)} className="px-4 py-2 rounded bg-orange-700 disabled:opacity-40">Plex-Poster zurücksetzen</button>
    </div>
    {imdbJob && <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-3">
      <h3 className="font-semibold">IMDb-Protokoll · {imdbJob.phase}</h3>
      <p className="text-xs text-gray-400">{imdbJob.scanned || 0} Einträge · {imdbJob.matched || 0} IMDb-Titel · {imdbJob.changed || 0} geänderte Werte · {imdbJob.rendered || 0} Poster gerendert</p>
      {imdbJob.is_running && <div role="progressbar" aria-valuenow={imdbJob.percent || 0} aria-valuemin="0" aria-valuemax="100" className="bg-gray-900 rounded h-4 overflow-hidden"><div className="bg-blue-600 h-full" style={{ width: `${imdbJob.percent || 0}%` }} /></div>}
      {imdbJob.error && <p role="alert" className="text-red-300 text-sm">{imdbJob.error}</p>}
      <div className="max-h-80 overflow-auto space-y-1 text-sm" role="log">{(imdbJob.logs || []).map(row => <div key={row.key} className="flex flex-wrap gap-x-3 gap-y-1 border-b border-gray-700 py-1">
        <span className="flex-1 min-w-44">{row.type === 'episode' ? 'Episode · ' : row.type === 'show' ? 'Serie · ' : 'Film · '}{row.title}</span>
        <span className="text-gray-300">{row.imdb_id || 'Keine IMDb-ID'}: {row.rating == null ? 'keine Wertung' : row.rating.toFixed(1)}</span>
        <span className={row.changed ? 'text-amber-300' : 'text-gray-400'}>{row.changed ? `${row.previous.toFixed(1)} → ${row.rating.toFixed(1)} (geändert)` : row.previous == null && row.rating != null ? 'neu im Cache' : 'unverändert'}</span>
        {row.render && <span className="text-blue-300">Poster: {row.render}</span>}
      </div>)}</div>
    </div>}
    {confirmReset && <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"><div className="bg-gray-800 border border-gray-600 rounded-xl p-6 max-w-md space-y-4">
      <h3 className="text-lg font-semibold">Plex-Poster zurücksetzen?</h3>
      <p className="text-sm text-gray-300">Für die Auswahl wird das erste verfügbare Poster ohne Upload aus Plex gewählt. Einträge ohne solches Poster werden übersprungen.</p>
      <div className="flex gap-3"><button onClick={() => setConfirmReset(false)} className="px-4 py-2 bg-gray-700 rounded">Abbrechen</button><button disabled={busy} onClick={() => launch(true)} className="px-4 py-2 bg-orange-700 rounded">{selected.length} Einträge zurücksetzen</button></div>
    </div></div>}
  </section>
}
