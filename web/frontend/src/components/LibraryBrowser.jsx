import { useEffect, useState } from 'react'

export default function LibraryBrowser({ onStartProcessing }) {
  const [libraries, setLibraries] = useState([])
  const [library, setLibrary] = useState('')
  const [parent, setParent] = useState(null)
  const [page, setPage] = useState(1)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const [busy, setBusy] = useState(false)

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
    const query = new URLSearchParams({ page: String(page) })
    if (parent) query.set('parent_key', parent.key)
    fetch(`/api/library/${encodeURIComponent(library)}/browse?${query}`)
      .then(async r => { const data = await r.json(); if (!r.ok) throw Error(data.detail || 'Library unavailable'); return data })
      .then(data => { if (active) { setItems(data.items); setTotal(data.total) } })
      .catch(e => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [library, parent, page])

  const switchLibrary = name => { setLibrary(name); setParent(null); setPage(1); setSelected([]) }
  const openShow = item => { setParent(item); setPage(1); setSelected([]) }
  const toggle = key => setSelected(previous => previous.includes(key) ? previous.filter(k => k !== key) : [...previous, key])
  const allVisible = items.length > 0 && items.every(item => selected.includes(item.key))
  const launch = async reset => {
    if (!selected.length || busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(reset ? '/api/restore' : '/api/process', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ library_name: library, rating_keys: selected, force: true, reset_to_plex: reset }),
      })
      const data = await response.json()
      if (!response.ok || data.error || data.status !== 'started') throw Error(data.error || data.detail || 'Could not start')
      setConfirmReset(false)
      onStartProcessing()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return <section className="space-y-5 text-gray-200">
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <h2 className="font-semibold text-lg mb-2">Bibliotheken durchsuchen</h2>
      <p className="text-sm text-gray-400 mb-4">Eine Serie wählt ihr Hauptposter. Öffne sie, um einzelne Staffeln auszuwählen; eine Staffel bearbeitet ihre Episodenbilder.</p>
      <div className="flex flex-wrap gap-2">{libraries.map(lib => <button key={lib.name} onClick={() => switchLibrary(lib.name)}
        className={`px-3 py-2 rounded border ${library === lib.name ? 'bg-blue-700 border-blue-500' : 'bg-gray-900 border-gray-600 hover:border-gray-400'}`}>{lib.name}</button>)}</div>
      {parent && <button className="text-blue-300 mt-4 hover:underline" onClick={() => { setParent(null); setPage(1); setSelected([]) }}>← {library} / {parent.title}</button>}
    </div>
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <div className="flex flex-wrap gap-3 justify-between items-center mb-4">
        <span>{loading ? 'Lade Einträge…' : `${total} ${parent ? 'Staffeln' : 'Einträge'}`}</span>
        <button disabled={!items.length} onClick={() => setSelected(previous => allVisible ? previous.filter(k => !items.some(item => item.key === k)) : [...new Set([...previous, ...items.map(item => item.key)])])}
          className="text-sm text-blue-300 disabled:text-gray-600">{allVisible ? 'Sichtbare abwählen' : 'Sichtbare auswählen'}</button>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">{items.map(item => <div key={item.key} className={`rounded border p-3 flex items-center gap-3 ${selected.includes(item.key) ? 'border-blue-500 bg-blue-950/30' : 'border-gray-600 bg-gray-900'}`}>
        <input type="checkbox" aria-label={`${item.title} auswählen`} checked={selected.includes(item.key)} onChange={() => toggle(item.key)} />
        <span className="flex-1 min-w-0 truncate" title={item.title}>{item.type === 'season' ? `Staffel ${item.index ?? '–'} · ` : ''}{item.title} {item.year ? `(${item.year})` : ''}</span>
        {item.type === 'show' && <button className="text-blue-300 text-sm shrink-0" onClick={() => openShow(item)}>Staffeln →</button>}
      </div>)}</div>
      {total > 60 && <div className="flex items-center gap-4 mt-5"><button disabled={page === 1} onClick={() => setPage(page - 1)}>← Zurück</button><span>Seite {page} / {Math.ceil(total / 60)}</span><button disabled={page * 60 >= total} onClick={() => setPage(page + 1)}>Weiter →</button></div>}
    </div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 flex flex-wrap items-center gap-3">
      <span className="text-sm mr-auto">{selected.length} ausgewählt</span>
      <button disabled={!selected.length || busy} onClick={() => launch(false)} className="px-4 py-2 rounded bg-blue-600 disabled:opacity-40">Overlays erneut anwenden</button>
      <button disabled={!selected.length || busy} onClick={() => setConfirmReset(true)} className="px-4 py-2 rounded bg-orange-700 disabled:opacity-40">Plex-Poster zurücksetzen</button>
    </div>
    {confirmReset && <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"><div className="bg-gray-800 border border-gray-600 rounded-xl p-6 max-w-md space-y-4">
      <h3 className="text-lg font-semibold">Plex-Poster zurücksetzen?</h3>
      <p className="text-sm text-gray-300">Für die Auswahl wird das erste verfügbare Poster ohne Upload aus Plex gewählt. Einträge ohne solches Poster werden übersprungen.</p>
      <div className="flex gap-3"><button onClick={() => setConfirmReset(false)} className="px-4 py-2 bg-gray-700 rounded">Abbrechen</button><button disabled={busy} onClick={() => launch(true)} className="px-4 py-2 bg-orange-700 rounded">{selected.length} Einträge zurücksetzen</button></div>
    </div></div>}
  </section>
}
