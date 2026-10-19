import { useEffect, useState } from 'react'

const names = {
  process: 'Overlays anwenden', batch: 'Bibliotheken bearbeiten', restore: 'Plex-Poster wiederherstellen',
  imdb: 'IMDb-Wertungen aktualisieren', selected_imdb: 'Ausgewählte IMDb-Wertungen',
  conflict: 'Kometa-Konflikte bearbeiten', webhook: 'Plex-Webhook',
  fresh_posters: 'Frische Plex-Poster', library_scan: 'Bibliothek scannen',
}

const statusText = { queued: 'Wartet', running: 'Läuft', completed: 'Fertig', failed: 'Fehlgeschlagen' }

// Every task reports the same progress shape (see docs/KONZEPT.md, section 3).
function TaskProgress({ task }) {
  const p = task.progress
  if (!p) return null
  const percent = p.percent ?? Math.min(100, Math.round(100 * (p.done || 0) / Math.max(1, p.total || 1)))
  const extra = task.live?.extra || {}
  const details = [
    p.phase,
    p.total ? `${p.done || 0}/${p.total}` : null,
    p.success ? `${p.success} erfolgreich` : null,
    p.skipped ? `${p.skipped} übersprungen` : null,
    p.failed ? `${p.failed} fehlgeschlagen` : null,
    extra.bytes_total ? `${(extra.bytes_downloaded / 1048576).toFixed(0)} / ${(extra.bytes_total / 1048576).toFixed(0)} MiB` : null,
    p.current,
  ].filter(Boolean)
  return <div className="mt-2 text-xs text-gray-400" role="progressbar" aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100">
    {details.join(' · ')}
    {task.status === 'running' && <div className="bg-gray-700 rounded h-1.5 mt-1"><div className="bg-blue-500 h-1.5 rounded" style={{ width: `${percent}%` }} /></div>}
  </div>
}

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const queue = await fetch('/api/tasks').then(response => response.json())
        if (active) { setTasks(queue.tasks || []); setError('') }
      } catch (exc) { if (active) setError(exc.message) }
    }
    load()
    const timer = setInterval(load, 2000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  return <section className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-4 text-gray-200">
    <h2 className="text-lg font-semibold">Aufgaben</h2>
    <p className="text-sm text-gray-400">Wartende und beim Neustart unterbrochene Aufgaben werden nacheinander fortgesetzt. Die angezeigten Ergebnisse bleiben gespeichert.</p>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {tasks.length === 0 && <p className="text-sm text-gray-400">Noch keine Aufgaben vorhanden.</p>}
    <div className="divide-y divide-gray-700">{tasks.map(task => <div key={task.id} className="py-3 flex flex-wrap gap-2 justify-between text-sm">
      <div className="min-w-0"><span className="font-medium">#{task.id} · {names[task.kind] || task.kind}</span>
        <span className="text-gray-400 ml-2">{task.payload.library_name || task.payload.library || (task.payload.library_names || task.payload.libraries || []).join(', ')}</span>
        {task.error && <p className="text-red-300 text-xs">{task.error}</p>}
        <TaskProgress task={task} />
      </div>
      <div className="text-gray-400">{statusText[task.status] || task.status} · {new Date(task.created_at * 1000).toLocaleString()} {task.attempts > 1 ? `· Versuch ${task.attempts}` : ''}</div>
    </div>)}</div>
  </section>
}
