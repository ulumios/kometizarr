import { useEffect, useState } from 'react'

const badge = {
  ok: ['bg-green-900 text-green-300', 'OK'],
  warning: ['bg-yellow-900 text-yellow-300', 'Achtung'],
  error: ['bg-red-900 text-red-300', 'Fehler'],
  missing: ['bg-gray-700 text-gray-300', 'Nicht eingerichtet'],
}

const time = value => value ? new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString() : '–'

export default function Status() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const load = async (refresh = false) => {
    setLoading(true)
    try { setData(await fetch(`/api/health${refresh ? '?refresh=true' : ''}`).then(r => r.json())) } finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    const timer = setInterval(() => load(), 15000)
    return () => clearInterval(timer)
  }, [])

  if (!data) return <p className="text-gray-400">{loading ? 'Prüfe …' : 'Status nicht verfügbar'}</p>
  const queue = data.queue
  return <div className="space-y-6 text-gray-200">
    <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-white font-semibold">🩺 Verbindungen und Daten</h2>
        <button onClick={() => load(true)} disabled={loading} className="bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded px-3 py-1 text-sm">
          {loading ? 'Prüfe …' : 'Jetzt prüfen'}</button>
      </div>
      <p className="text-xs text-gray-400">Externe Dienste werden höchstens alle 5 Minuten geprüft · zuletzt {time(data.checked_at)}</p>
      <ul className="divide-y divide-gray-700">{data.checks.map(check => {
        const [style, label] = badge[check.state] || badge.missing
        return <li key={check.name} className="py-2 flex flex-wrap gap-3 items-center text-sm">
          <span className={`text-xs rounded px-2 py-0.5 w-32 text-center ${style}`}>{label}</span>
          <span className="font-medium w-48">{check.name}</span>
          <span className="text-gray-400 flex-1 min-w-0 break-words">{check.detail}{check.ms ? ` · ${check.ms} ms` : ''}</span>
        </li>
      })}</ul>
    </section>

    <section className="bg-gray-800 border border-gray-700 rounded-xl p-6 grid gap-4 sm:grid-cols-2">
      <div>
        <h3 className="font-semibold mb-2">Warteschlange</h3>
        <p className="text-sm text-gray-300">{queue.queued} wartend · {queue.completed_24h} fertig und {queue.failed_24h} fehlgeschlagen in 24 h</p>
        {queue.running && <p className="text-sm text-blue-300 mt-1">Läuft: #{queue.running.task_id} {queue.running.kind}
          {queue.running.library ? ` · ${queue.running.library}` : ''} · {queue.running.percent}%</p>}
      </div>
      <div>
        <h3 className="font-semibold mb-2">Zeitplan</h3>
        <dl className="text-sm text-gray-300 grid grid-cols-[auto,1fr] gap-x-3">
          <dt className="text-gray-400">Normaler Lauf</dt><dd>{time(data.schedule.cron_normal)}</dd>
          <dt className="text-gray-400">Force-Lauf</dt><dd>{time(data.schedule.cron_force)}</dd>
          <dt className="text-gray-400">IMDb-Aktualisierung</dt><dd>{time(data.schedule.imdb_refresh)}</dd>
        </dl>
      </div>
    </section>

    <section className="bg-gray-800 border border-gray-700 rounded-xl p-6">
      <h3 className="font-semibold mb-2">Letzte Webhooks</h3>
      {data.webhooks.length === 0 ? <p className="text-sm text-gray-400">Seit dem letzten Start keine Webhooks empfangen.</p> :
        <ul className="text-sm divide-y divide-gray-700">{data.webhooks.map((hook, index) => <li key={index} className="py-1.5 flex flex-wrap gap-3">
          <span className="text-gray-400 w-40">{time(hook.at)}</span>
          <span className="w-16">{hook.source}</span>
          <span className="flex-1 min-w-0">{[hook.library, hook.title].filter(Boolean).join(' · ') || hook.event}</span>
          <span className="text-gray-400">{hook.status}</span>
        </li>)}</ul>}
    </section>
  </div>
}
