import { useEffect, useState } from 'react'

const names = {
  process: 'Overlays anwenden', batch: 'Bibliotheken bearbeiten', restore: 'Plex-Poster wiederherstellen',
  imdb: 'IMDb-Wertungen aktualisieren', selected_imdb: 'Ausgewählte IMDb-Wertungen',
  conflict: 'Kometa-Konflikte bearbeiten', webhook: 'Plex-Webhook',
}

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [imdb, setImdb] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [queue, imdbState] = await Promise.all([
          fetch('/api/tasks').then(response => response.json()),
          fetch('/api/imdb-sync/status').then(response => response.json()),
        ])
        if (active) { setTasks(queue.tasks || []); setImdb(imdbState); setError('') }
      } catch (exc) { if (active) setError(exc.message) }
    }
    load()
    const timer = setInterval(load, 3000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  return <section className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-4 text-gray-200">
    <h2 className="text-lg font-semibold">Aufgaben</h2>
    <p className="text-sm text-gray-400">Wartende und beim Neustart unterbrochene Aufgaben werden nacheinander fortgesetzt. Die angezeigten Ergebnisse bleiben gespeichert.</p>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {imdb?.is_running && <div className="bg-gray-900 p-3 rounded text-sm" role="progressbar" aria-valuenow={imdb.percent || 0} aria-valuemin="0" aria-valuemax="100">
      <div>IMDb · {imdb.phase} · {imdb.percent || 0}%</div>
      <div className="w-full bg-gray-700 rounded h-2 mt-2"><div className="bg-blue-500 rounded h-2" style={{ width: `${imdb.percent || 0}%` }} /></div>
      <div className="text-xs text-gray-400 mt-1">{imdb.matched || 0} Werte · {imdb.rendered || 0} Poster · {imdb.bytes_total ? `${(imdb.bytes_downloaded / 1048576).toFixed(0)} / ${(imdb.bytes_total / 1048576).toFixed(0)} MiB geladen` : ''}</div>
    </div>}
    {tasks.length === 0 && <p className="text-sm text-gray-400">Noch keine Aufgaben vorhanden.</p>}
    <div className="divide-y divide-gray-700">{tasks.map(task => <div key={task.id} className="py-3 flex flex-wrap gap-2 justify-between text-sm">
      <div><span className="font-medium">#{task.id} · {names[task.kind] || task.kind}</span>
        <span className="text-gray-400 ml-2">{task.payload.library_name || task.payload.library || ''}</span>
        {task.error && <p className="text-red-300 text-xs">{task.error}</p>}
      </div>
      <div className="text-gray-400">{task.status === 'queued' ? 'Wartet' : task.status === 'running' ? 'Läuft' : task.status === 'completed' ? 'Fertig' : 'Fehlgeschlagen'} · {new Date(task.created_at * 1000).toLocaleString()} {task.attempts > 1 ? `· Versuch ${task.attempts}` : ''}</div>
    </div>)}</div>
  </section>
}
