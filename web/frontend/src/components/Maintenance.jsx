import { useEffect, useState } from 'react'

const formatBytes = bytes => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const power = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** power).toFixed(power ? 1 : 0)} ${units[power]}`
}

const post = (url, body) => fetch(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
}).then(async response => ({ ok: response.ok, data: await response.json() }))

// Poll a queued task until it is finished.
const waitFor = taskId => new Promise(resolve => {
  const timer = setInterval(async () => {
    const { status } = await fetch(`/api/tasks/${taskId}/status`).then(r => r.json()).catch(() => ({}))
    if (status && status !== 'queued' && status !== 'running') { clearInterval(timer); resolve(status) }
  }, 1500)
})

export default function Maintenance({ onOpenTasks }) {
  const [overview, setOverview] = useState(null)
  const [audit, setAudit] = useState({ reports: [] })
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [libraries, setLibraries] = useState([])
  const [uploadLibs, setUploadLibs] = useState([])

  const loadOverview = () => fetch('/api/maintenance/overview').then(r => r.json()).then(setOverview).catch(() => {})
  const loadAudit = () => fetch('/api/maintenance/audit/latest').then(r => r.json()).then(setAudit).catch(() => {})

  useEffect(() => {
    loadOverview()
    loadAudit()
    fetch('/api/libraries').then(r => r.json()).then(d => setLibraries((d.libraries || [])
      .filter(lib => lib.type === 'movie' || lib.type === 'show'))).catch(() => {})
  }, [])

  const run = async (label, url, body, after) => {
    setBusy(label); setMessage('')
    const { ok, data } = await post(url, body)
    if (!ok) { setMessage(data.detail || 'Nicht möglich'); setBusy(''); return }
    setMessage(`Aufgabe #${data.task_id} läuft …`)
    const status = await waitFor(data.task_id)
    setMessage(`Aufgabe #${data.task_id}: ${status === 'completed' ? 'fertig' : 'fehlgeschlagen'} – Details unter „Aufgaben“.`)
    setBusy('')
    after?.()
  }

  const deleteOrphans = report => {
    const paths = report.orphans.map(orphan => orphan.path)
    if (!confirm(`${paths.length} verwaiste Backup-Ordner in „${report.library}“ löschen (${formatBytes(report.orphan_bytes)})?`)) return
    run('cleanup', '/api/maintenance/cleanup', { library: report.library, paths }, () => { loadOverview(); loadAudit() })
  }

  const cleanUploads = dryRun => {
    if (!dryRun && !confirm('Nicht ausgewählte, früher hochgeladene Poster werden aus den Plex-Metadaten gelöscht. Das lässt sich nicht rückgängig machen. Fortfahren?')) return
    run(dryRun ? 'uploads-dry' : 'uploads', '/api/maintenance/plex-uploads', { libraries: uploadLibs, dry_run: dryRun })
  }

  return <div className="space-y-6 text-gray-200">
    <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
      <h2 className="text-white font-semibold">💾 Backups</h2>
      {overview && <p className="text-sm text-gray-400">
        Belegt: {formatBytes(overview.total_bytes)}{overview.disk_total ? ` · frei auf dem Laufwerk: ${formatBytes(overview.disk_free)} von ${formatBytes(overview.disk_total)}` : ''}
      </p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-gray-400 text-left"><tr>
            <th className="py-1 pr-4 font-medium">Bibliothek</th><th className="py-1 pr-4 font-medium text-right">Größe</th>
            <th className="py-1 pr-4 font-medium text-right">Originale</th><th className="py-1 font-medium text-right">Overlays</th>
          </tr></thead>
          <tbody>{(overview?.libraries || []).map(entry => <tr key={entry.library} className="border-t border-gray-700">
            <td className="py-1 pr-4">{entry.library}</td><td className="py-1 pr-4 text-right tabular-nums">{formatBytes(entry.bytes)}</td>
            <td className="py-1 pr-4 text-right tabular-nums">{entry.originals}</td><td className="py-1 text-right tabular-nums">{entry.overlays}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <button disabled={!!busy} onClick={() => run('audit', '/api/maintenance/audit', { libraries: [] }, loadAudit)}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 rounded px-4 py-2 text-sm">
        {busy === 'audit' ? 'Prüfe …' : 'Verwaiste Backups suchen'}
      </button>
      {audit.reports.length > 0 && <div className="space-y-2">
        <p className="text-xs text-gray-400">Letzte Prüfung (Aufgabe #{audit.task_id}). Verwaist = Titel oder Episode gibt es in Plex nicht mehr.</p>
        {audit.reports.map(report => <div key={report.library} className="bg-gray-900 rounded p-3 text-sm flex flex-wrap gap-3 items-center justify-between">
          <div>
            <span className="font-medium">{report.library}</span>
            {report.error ? <span className="text-red-300 ml-2">{report.error}</span> : <span className="text-gray-400 ml-2">
              {report.orphan_count} verwaist ({formatBytes(report.orphan_bytes)}){report.legacy_count ? ` · ${report.legacy_count} noch im alten Layout (werden beim nächsten Zugriff verschoben)` : ''}
            </span>}
          </div>
          {report.orphans?.length > 0 && <button disabled={!!busy} onClick={() => deleteOrphans(report)}
            className="bg-red-700 hover:bg-red-800 disabled:opacity-40 rounded px-3 py-1 text-xs">Verwaiste löschen</button>}
        </div>)}
      </div>}
    </section>

    <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
      <h2 className="text-white font-semibold">🧹 Alte Poster-Uploads in Plex</h2>
      <p className="text-sm text-gray-400">Plex behält jedes hochgeladene Poster. Ist der Ordner „Plex Media Server“ unter <code>/plex</code> eingebunden,
        findet Kometizarr nicht mehr ausgewählte Uploads und kann sie löschen. Es werden nur Dateien gelöscht, die Plex selbst als nicht
        ausgewählten Upload des Titels meldet.</p>
      {overview && !overview.plex_data_dir && <p className="text-sm text-yellow-300">Plex-Datenordner nicht gefunden – nur die Plex-Aufräumfunktionen unten sind verfügbar.</p>}
      {overview?.plex_data_dir && <>
        <div className="flex flex-wrap gap-2">{libraries.map(lib => {
          const checked = uploadLibs.includes(lib.name)
          return <label key={lib.name} className={`text-sm px-3 py-1 rounded border cursor-pointer ${checked ? 'bg-blue-900 border-blue-500' : 'border-gray-600'}`}>
            <input type="checkbox" className="mr-2" checked={checked}
              onChange={() => setUploadLibs(prev => checked ? prev.filter(name => name !== lib.name) : [...prev, lib.name])} />{lib.name}
          </label>
        })}</div>
        <div className="flex flex-wrap gap-2">
          <button disabled={!!busy || !uploadLibs.length} onClick={() => cleanUploads(true)}
            className="bg-gray-600 hover:bg-gray-500 disabled:opacity-40 rounded px-4 py-2 text-sm">Trockenlauf</button>
          <button disabled={!!busy || !uploadLibs.length} onClick={() => cleanUploads(false)}
            className="bg-red-700 hover:bg-red-800 disabled:opacity-40 rounded px-4 py-2 text-sm">Alte Uploads löschen</button>
        </div>
      </>}
      <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-700">
        {[['clean_bundles', 'Bundles bereinigen'], ['empty_trash', 'Papierkorb leeren'], ['optimize', 'Datenbank optimieren']].map(([action, label]) =>
          <button key={action} disabled={!!busy} onClick={() => run(action, '/api/maintenance/plex', { action })}
            className="bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded px-3 py-1.5 text-sm">{label}</button>)}
      </div>
    </section>

    {message && <p role="status" className="text-sm text-blue-300">{message} {onOpenTasks &&
      <button onClick={onOpenTasks} className="underline">Aufgaben öffnen</button>}</p>}
  </div>
}
