import { useEffect, useState } from 'react'
import { kometaCount, kometaQuestion } from './kometaReset'

const names = {
  process: 'Overlays anwenden', batch: 'Bibliotheken bearbeiten', restore: 'Plex-Poster wiederherstellen',
  imdb: 'IMDb-Wertungen aktualisieren', selected_imdb: 'Ausgewählte IMDb-Wertungen',
  conflict: 'Kometa-Konflikte bearbeiten', webhook: 'Plex-Webhook',
  fresh_posters: 'Frische Plex-Poster', library_scan: 'Bibliothek scannen', plan: 'Vorschau eines Laufs',
  backup_audit: 'Backups prüfen', backup_cleanup: 'Verwaiste Backups löschen',
  plex_uploads: 'Alte Plex-Uploads', plex_maintenance: 'Plex-Wartung', arr: 'Sonarr/Radarr-Import',
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

const mib = bytes => `${((bytes || 0) / 1048576).toFixed(1)} MiB`

// One line for maintenance tasks, from the numbers they store in progress.extra.
function MaintenanceResult({ task }) {
  const extra = task.progress?.extra || {}
  if (task.kind === 'plex_uploads' && extra.files !== undefined)
    return <p className="mt-1 text-xs text-gray-300">{extra.files} alte Uploads ({mib(extra.bytes)}) {extra.dry_run ? 'gefunden (Trockenlauf)' : 'gelöscht'}</p>
  if (task.kind === 'backup_cleanup' && extra.deleted)
    return <p className="mt-1 text-xs text-gray-300">{extra.deleted.length} Ordner gelöscht, {mib(extra.freed_bytes)} frei</p>
  if (task.kind === 'backup_audit' && extra.reports)
    return <p className="mt-1 text-xs text-gray-300">{extra.reports.map(r => `${r.library}: ${r.error ? 'Fehler' : `${r.orphan_count} verwaist`}`).join(' · ')}</p>
  return null
}

// Summary of a finished preview: how many items end up in which outcome.
function PlanSummary({ task }) {
  const summary = task.progress?.extra?.summary
  if (task.kind !== 'plan' || !summary) return null
  return <ul className="mt-2 text-xs text-gray-300 space-y-0.5">
    {Object.entries(summary).sort((a, b) => b[1] - a[1]).map(([reason, count]) =>
      <li key={reason}><span className="inline-block w-12 text-right mr-2 tabular-nums">{count}</span>{reason}</li>)}
  </ul>
}

const itemLabel = item => item.type === 'episode'
  ? `${item.series ? `${item.series} · ` : ''}S${String(item.season ?? 0).padStart(2, '0')}E${String(item.index ?? 0).padStart(2, '0')} · ${item.title}`
  : item.type === 'season' ? `${item.series || item.path?.[0]?.title || ''} · Staffel ${item.index ?? '–'}`
  : `${item.title}${item.year ? ` (${item.year})` : ''}`

// Touched items of a task; a click opens the item in the library browser for a manual check
function TaskItems({ task, onOpenInLibrary }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const toggle = async () => {
    setOpen(!open)
    if (open || data) return
    try {
      const response = await fetch(`/api/tasks/${task.id}/items`)
      if (!response.ok) throw Error('Einträge konnten nicht geladen werden')
      setData(await response.json())
    } catch (e) { setError(e.message) }
  }
  const go = item => onOpenInLibrary({ library: item.library, path: item.path, key: item.key, taskId: task.id })
  return <div className="mt-2">
    <button onClick={toggle} className="text-xs text-blue-300 hover:underline">{open ? '▾ Einträge ausblenden' : '▸ Einträge anzeigen'}</button>
    {open && <div className="mt-2 space-y-1">
      {error && <p className="text-xs text-red-300">{error}</p>}
      {!data && !error && <p className="text-xs text-gray-400">Lade…</p>}
      {data && data.items.length === 0 && <p className="text-xs text-gray-400">Keine Einträge gespeichert (unveränderte Poster werden nur gezählt).</p>}
      {data && data.items.length > 0 && <>
        <button onClick={() => go({ ...data.items[0], path: [], key: null })} className="text-xs bg-gray-700 hover:bg-gray-600 rounded px-2 py-1">
          Alle in der Bibliothek anzeigen</button>
        <ul className="max-h-72 overflow-auto divide-y divide-gray-700/60 text-xs">{data.items.map(item => <li key={item.key}>
          <button onClick={() => go(item)} className="w-full text-left py-1.5 flex flex-wrap gap-x-3 hover:bg-gray-700/40 rounded px-1">
            <span className="text-blue-200 min-w-0 break-words">{itemLabel(item)}</span>
            {item.result && <span className={/fehl|nicht|Kometa/.test(item.result) ? 'text-amber-300' : 'text-gray-400'}>{item.result}</span>}
          </button></li>)}</ul>
        {data.missing > 0 && <p className="text-xs text-gray-500">{data.missing} Einträge fehlen im Bibliotheksindex (Bibliothek neu scannen).</p>}
      </>}
    </div>}
  </div>
}

export default function Tasks({ onOpenInLibrary }) {
  const [tasks, setTasks] = useState([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const follow = async (task, action) => {
    const response = await fetch(`/api/tasks/${task.id}/${action}`, { method: 'POST' })
    const data = await response.json()
    setMessage(response.ok ? `Aufgabe #${data.task_id} eingereiht` : (data.detail || 'Nicht möglich'))
  }
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
    {message && <p role="status" className="text-sm text-blue-300">{message}</p>}
    {tasks.length === 0 && <p className="text-sm text-gray-400">Noch keine Aufgaben vorhanden.</p>}
    <div className="divide-y divide-gray-700">{tasks.map(task => <div key={task.id} className="py-3 flex flex-wrap gap-2 justify-between text-sm">
      <div className="min-w-0"><span className="font-medium">#{task.id} · {names[task.kind] || task.kind}</span>
        <span className="text-gray-400 ml-2">{task.payload.library_name || task.payload.library || task.payload.target?.title || (task.payload.library_names || task.payload.libraries || []).join(', ')}</span>
        {task.error && <p className="text-red-300 text-xs">{task.error}</p>}
        <TaskProgress task={task} />
        <PlanSummary task={task} />
        <MaintenanceResult task={task} />
        {['process', 'webhook', 'restore', 'fresh_posters', 'imdb', 'selected_imdb', 'conflict', 'arr'].includes(task.kind) && task.status !== 'queued' &&
          (task.result_count > 0 || task.progress?.failed_keys?.length > 0 || task.payload?.rating_keys?.length > 0 || task.payload?.request?.rating_keys?.length > 0) &&
          <TaskItems task={task} onOpenInLibrary={onOpenInLibrary} />}
        <div className="flex gap-2 mt-2">
          {task.kind === 'plan' && task.status === 'completed' &&
            <button onClick={() => follow(task, 'run-plan')} className="bg-blue-600 hover:bg-blue-700 rounded px-3 py-1 text-xs">Plan ausführen</button>}
          {task.status !== 'running' && task.status !== 'queued' && task.progress?.failed_keys?.length > 0 && task.kind !== 'plan' &&
            <button onClick={() => follow(task, 'retry')} className="bg-orange-600 hover:bg-orange-700 rounded px-3 py-1 text-xs">
              {task.progress.failed_keys.length} fehlgeschlagene wiederholen</button>}
          {task.status !== 'running' && task.status !== 'queued' && kometaCount(task.progress) > 0 &&
            <button onClick={() => window.confirm(kometaQuestion(kometaCount(task.progress))) && follow(task, 'kometa-reset')}
              className="bg-amber-600 hover:bg-amber-700 rounded px-3 py-1 text-xs">
              {kometaCount(task.progress)} Kometa-Titel zurücksetzen und overlayen</button>}
        </div>
      </div>
      <div className="text-gray-400">{statusText[task.status] || task.status}{task.status === 'queued' && task.run_after * 1000 > Date.now()
        ? ` bis ${new Date(task.run_after * 1000).toLocaleTimeString()}` : ''} · {new Date(task.created_at * 1000).toLocaleString()} {task.attempts > 1 ? `· Versuch ${task.attempts}` : ''}</div>
    </div>)}</div>
  </section>
}
