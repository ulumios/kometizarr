// Items a run skipped because Kometa overlaid them, per library ({library: [keys]})
export const kometaCount = progress => Object.values(progress?.kometa_keys || {}).reduce((sum, keys) => sum + keys.length, 0)

export const kometaQuestion = count => `${count} ${count === 1 ? 'Eintrag wurde' : 'Einträge wurden'} übersprungen, weil Kometa erkannt wurde. ` +
  'Kometa-Overlay zurücksetzen (Kometas Original bzw. Plex-Agent-Poster) und neu overlayen?'

// Queues the skipped items again with the Kometa reset; returns the new task id
export async function startKometaReset(taskId) {
  const response = await fetch(`/api/tasks/${taskId}/kometa-reset`, { method: 'POST' })
  const data = await response.json()
  if (!response.ok) throw Error(data.detail || 'Zurücksetzen konnte nicht gestartet werden')
  return data.task_id
}
