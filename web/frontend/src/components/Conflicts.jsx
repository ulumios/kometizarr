import { useEffect, useMemo, useState } from 'react'

export default function Conflicts() {
  const [libraries, setLibraries] = useState([])
  const [library, setLibrary] = useState('')
  const [items, setItems] = useState([])
  const [selected, setSelected] = useState([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [posterVersion, setPosterVersion] = useState(() => Date.now())
  const [scanning, setScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState({ phase: '', percent: 0, processed: 0, total: 0, skipped: 0 })
  const [page, setPage] = useState(1)
  const [seriesFolder, setSeriesFolder] = useState(null)
  const pageSize = 60

  useEffect(() => {
    fetch('/api/libraries').then(r => r.json()).then(data => {
      const available = (data.libraries || []).filter(lib => ['movie', 'show'].includes(lib.type))
      setLibraries(available)
      setLibrary(current => current || available[0]?.name || '')
    }).catch(e => setError(e.message))
    fetch('/api/kometa/conflicts/status').then(r => r.json()).then(setStatus).catch(() => {})
  }, [])

  const refresh = async (libraryName = library, force = false, polling = false) => {
    if (!libraryName) return
    if (!polling) { setLoading(true); setError('') }
    try {
      const response = await fetch(`/api/kometa/conflicts?library_name=${encodeURIComponent(libraryName)}${force ? '&refresh=true' : ''}`)
      const body = await response.text()
      let data
      try { data = JSON.parse(body) } catch { throw Error(`Serverantwort ${response.status} statt JSON. Bitte Backend-Logs prüfen.`) }
      if (!response.ok || data.error) throw Error(data.detail || data.error || 'Konflikte konnten nicht geladen werden')
      setScanning(!!data.is_running)
      setScanProgress({ phase: data.phase || '', percent: data.percent || 0,
        processed: data.processed || 0, total: data.total || 0, skipped: data.skipped || 0 })
      setItems(data.items || [])
      if (!polling) { setSelected([]); setPosterVersion(Date.now()) }
    } catch (e) { setScanning(false); setError(e.message) }
    finally { if (!polling) setLoading(false) }
  }

  useEffect(() => { refresh(library) }, [library])

  useEffect(() => {
    if (!scanning || !library) return
    const timer = setInterval(() => refresh(library, false, true), 2000)
    return () => clearInterval(timer)
  }, [scanning, library])

  useEffect(() => {
    if (!status?.is_running) return
    const timer = setInterval(async () => {
      try {
        if (status.task_id) {
          const queue = await fetch('/api/tasks').then(r => r.json())
          const task = queue.tasks?.find(row => row.id === status.task_id)
          if (task?.status === 'queued') return
        }
        const current = await fetch('/api/kometa/conflicts/status').then(r => r.json())
        setStatus({ ...current, task_id: status.task_id })
      } catch (_) { /* Try again after the next interval. */ }
    }, 1500)
    return () => clearInterval(timer)
  }, [status?.is_running, status?.task_id])

  useEffect(() => {
    if (status?.phase === 'Abgeschlossen' && !status.is_running) refresh(library, true)
  }, [status?.is_running, status?.phase])

  const visible = useMemo(() => items.filter(item =>
    `${item.title} ${item.series || ''} ${item.year || ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [items, query])
  const grouped = useMemo(() => {
    if (seriesFolder) return visible.filter(item => item.type === 'episode' && item.series === seriesFolder)
    const output = visible.filter(item => item.type !== 'episode')
    const episodes = new Map()
    visible.filter(item => item.type === 'episode').forEach(item => {
      const name = item.series || 'Unbekannte Serie'
      if (!episodes.has(name)) episodes.set(name, [])
      episodes.get(name).push(item)
    })
    episodes.forEach((children, title) => output.push({
      key: `series:${title}`, type: 'series_group', title, series: title,
      children, conflict_count: children.length, poster_key: children[0]?.key,
    }))
    return output.sort((a, b) => a.title.localeCompare(b.title))
  }, [visible, seriesFolder])
  const pageItems = grouped.slice((page - 1) * pageSize, page * pageSize)
  const keysFor = item => item.type === 'series_group' ? item.children.map(child => child.key) : [item.key]
  const toggleItem = item => setSelected(previous => {
    const keys = keysFor(item)
    const remove = keys.every(key => previous.includes(key))
    return remove ? previous.filter(key => !keys.includes(key)) : [...new Set([...previous, ...keys])]
  })
  useEffect(() => setPage(1), [query, seriesFolder])

  const start = async action => {
    setConfirm(null)
    setError('')
    try {
      const response = await fetch('/api/kometa/conflicts/action', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ library_name: library, rating_keys: selected, action }),
      })
      const data = await response.json()
      if (!response.ok) throw Error(data.detail || 'Aktion konnte nicht gestartet werden')
      setStatus({ is_running: true, phase: `Aufgabe #${data.task_id} wartet`, task_id: data.task_id, total: selected.length, resolved: 0, skipped: 0, failed: 0 })
    } catch (e) { setError(e.message) }
  }

  return <section className="space-y-5 text-gray-200">
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-3">
      <h2 className="text-lg font-semibold">Kometa-Konflikte</h2>
      <p className="text-sm text-gray-400">Plex-Einträge mit dem Label „Overlay“ und Einträge, bei denen du das Label entfernt hast und noch ein anderes Poster in Plex auswählen musst. Ohne Label lässt sich ein Kometa-Poster nicht zuverlässig erkennen.</p>
      <div className="flex flex-wrap gap-2">{libraries.map(lib => <button key={lib.name}
        onClick={() => { setLibrary(lib.name); setSelected([]); setSeriesFolder(null); setPage(1) }}
        className={`rounded border px-3 py-2 text-sm ${library === lib.name ? 'border-blue-500 bg-blue-700' : 'border-gray-600 bg-gray-900'}`}>{lib.name}</button>)}</div>
      <div className="flex gap-3"><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Konflikte durchsuchen…"
        aria-label="Konflikte durchsuchen" className="bg-gray-900 border border-gray-600 rounded px-3 py-2 flex-1 text-sm" />
        </div>
      {scanning && <div className="space-y-1" role="progressbar" aria-valuenow={scanProgress.percent} aria-valuemin="0" aria-valuemax="100" aria-label="Konflikte durchsuchen">
        <div className="text-xs text-blue-200">{scanProgress.phase} · {scanProgress.percent}%{scanProgress.total ? ` · ${scanProgress.processed}/${scanProgress.total} geprüft` : ''}{scanProgress.skipped ? ` · ${scanProgress.skipped} nicht mehr in Plex` : ''}</div>
        <div className="h-2 rounded bg-gray-700 overflow-hidden"><div className="h-full bg-blue-500 transition-all" style={{ width: `${scanProgress.percent}%` }} /></div>
      </div>}
    </div>
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      {seriesFolder && <button className="text-blue-300 mb-4 hover:underline" onClick={() => { setSeriesFolder(null); setPage(1); setSelected([]) }}>← Konflikte / {seriesFolder}</button>}
      <div className="flex justify-between mb-4 text-sm"><span>{loading ? 'Lade…' : seriesFolder ? `${grouped.length} Episodenkonflikte` : `${grouped.length} Filme und Serien mit Konflikten`}</span>
        <button onClick={() => setSelected(previous => pageItems.flatMap(keysFor).every(key => previous.includes(key)) ? previous.filter(key => !pageItems.flatMap(keysFor).includes(key)) : [...new Set([...previous, ...pageItems.flatMap(keysFor)])])} className="text-blue-300">Sichtbare auswählen/abwählen</button></div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">{pageItems.map(item => <div key={item.key}
        className={`rounded-lg overflow-hidden text-left border ${keysFor(item).every(key => selected.includes(key)) ? 'border-blue-500' : 'border-gray-600'}`}>
        <button className="w-full text-left" onClick={() => toggleItem(item)}>
        <div className="relative aspect-[2/3] bg-gray-900"><span className="absolute inset-0 flex items-center justify-center text-xs">Kein Poster</span>
          <img loading="lazy" src={`/api/library/${encodeURIComponent(library)}/poster/${item.poster_key || item.key}?v=${posterVersion}`} alt="" className="absolute inset-0 w-full h-full object-cover" onError={e => { e.currentTarget.style.display = 'none' }} />
          <span className="absolute top-2 right-2 bg-gray-950/90 px-2 rounded">{keysFor(item).every(key => selected.includes(key)) ? '✓' : '○'}</span></div>
        <div className="p-2 text-sm"><div className="truncate">{item.type !== 'series_group' && item.series && `${item.series} · `}{item.title}</div>
          <div className="text-xs text-amber-300">{item.type === 'series_group' ? `${item.conflict_count} Episodenkonflikte` : item.pending_manual ? 'Wartet auf neues Plex-Poster' : item.manual_ready ? 'Neues Plex-Poster erkannt · bereit' : item.has_kometizarr_overlay ? 'Kometa-Label + Kometizarr-Overlay' : 'Kometa-Label'}</div></div>
        </button>
        {item.type === 'series_group' && <button className="px-2 pb-2 text-xs text-blue-300 hover:underline" onClick={() => { setSeriesFolder(item.series); setPage(1); setSelected([]) }}>Episoden anzeigen →</button>}
      </div>)}</div>
      {grouped.length > pageSize && <div className="flex gap-4 mt-5"><button disabled={page === 1} onClick={() => setPage(page - 1)}>← Zurück</button><span>Seite {page} / {Math.ceil(grouped.length / pageSize)}</span><button disabled={page * pageSize >= grouped.length} onClick={() => setPage(page + 1)}>Weiter →</button></div>}
    </div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-3">
      <p className="text-sm">{selected.length} ausgewählt</p>
      <div className="flex flex-wrap gap-3">
        <button disabled={!selected.length || status?.is_running} onClick={() => setConfirm('reset_render')} className="rounded bg-blue-600 px-4 py-2 text-sm disabled:opacity-40">Agent-Poster wählen und Overlay anwenden</button>
        <button disabled={!selected.length || status?.is_running} onClick={() => setConfirm('remove_label')} className="rounded bg-orange-700 px-4 py-2 text-sm disabled:opacity-40">Nur Kometa-Label entfernen</button>
      </div>
      <p className="text-xs text-gray-400">Nach „Nur Label entfernen“ bleibt das Poster erhalten. Kometizarr wartet, bis du in Plex ein anderes Poster auswählst. Falls Plex kein Agent-Poster anbietet, wird der Reset übersprungen.</p>
      {status && <div className="text-sm text-gray-300">{status.phase} · {status.resolved || 0} erledigt · {status.skipped || 0} übersprungen · {status.failed || 0} fehlgeschlagen</div>}
      {status?.error && <p role="alert" className="text-red-300 text-sm">{status.error}</p>}
      {status?.results && Object.keys(status.results).length > 0 && <div className="text-xs text-gray-400 max-h-32 overflow-y-auto">{Object.entries(status.results).map(([key, result]) => <div key={key}>{items.find(item => item.key === key)?.title || key}: {result}</div>)}</div>}
    </div>
    {confirm && <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"><div className="bg-gray-800 border border-gray-600 rounded-xl p-5 max-w-md space-y-4">
      <h3 className="font-semibold">{selected.length} Plex-Einträge bearbeiten?</h3>
      <p className="text-sm text-gray-300">{confirm === 'reset_render' ? 'Für jeden Eintrag wird ein Plex-Agent-Poster ausgewählt und anschließend das Kometizarr-Overlay erstellt.' : 'Das Overlay-Label wird entfernt. Wähle danach für diese Einträge manuell ein anderes Poster in Plex.'}</p>
      <div className="flex gap-3"><button className="bg-gray-700 rounded px-3 py-2" onClick={() => setConfirm(null)}>Abbrechen</button><button className="bg-blue-600 rounded px-3 py-2" onClick={() => start(confirm)}>Ausführen</button></div>
    </div></div>}
  </section>
}
