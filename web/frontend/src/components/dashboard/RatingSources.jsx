export default function RatingSources({ design }) {
  const { ratingSources, mediaOverlay, setMediaOverlay, toggleRatingSource, toggleMediaOverlay, savePositionsSoon } = design
  return (
    <div>
      <label className="block text-sm font-medium mb-2">Rating Sources to Display</label>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center">
          <input
            type="checkbox"
            checked={ratingSources.tmdb}
            onChange={() => toggleRatingSource('tmdb')}
            className="mr-2"
            id="tmdb-checkbox"
          />
          <label htmlFor="tmdb-checkbox" className="text-sm">
            🎬 TMDB (0-10 scale)
          </label>
        </div>
        <div className="flex items-center">
          <input
            type="checkbox"
            checked={ratingSources.imdb}
            onChange={() => toggleRatingSource('imdb')}
            className="mr-2"
            id="imdb-checkbox"
          />
          <label htmlFor="imdb-checkbox" className="text-sm">
            ⭐ IMDb (0-10 scale)
          </label>
        </div>
        <div className="flex items-center">
          <input
            type="checkbox"
            checked={ratingSources.rt_critic}
            onChange={() => toggleRatingSource('rt_critic')}
            className="mr-2"
            id="rt-critic-checkbox"
          />
          <label htmlFor="rt-critic-checkbox" className="text-sm">
            🍅 RT Critic (0-100%)
          </label>
        </div>
        <div className="flex items-center">
          <input
            type="checkbox"
            checked={ratingSources.rt_audience}
            onChange={() => toggleRatingSource('rt_audience')}
            className="mr-2"
            id="rt-audience-checkbox"
          />
          <label htmlFor="rt-audience-checkbox" className="text-sm">
            🍿 RT Audience (0-100%)
          </label>
        </div>
        <div className="flex items-center">
          <input type="checkbox" checked={mediaOverlay.source} onChange={() => toggleMediaOverlay('source')} className="mr-2" id="source-checkbox" />
          <label htmlFor="source-checkbox" className="text-sm">🏷️ Source badge (BluRay / PreRelease)</label>
        </div>
        <div className="flex items-center">
          <input type="checkbox" checked={mediaOverlay.languages} onChange={() => toggleMediaOverlay('languages')} className="mr-2" id="languages-checkbox" />
          <label htmlFor="languages-checkbox" className="text-sm">🌐 Episode languages</label>
        </div>
        <div className="flex items-center">
          <input type="checkbox" checked={mediaOverlay.status} onChange={() => toggleMediaOverlay('status')} className="mr-2" id="status-checkbox" />
          <label htmlFor="status-checkbox" className="text-sm">📺 Serienstatus</label>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
        {[['bluray', 'BluRay'], ['prerelease', 'PreRelease']].map(([key, label]) => (
          <label key={key} className="text-gray-400">{label} label
            <input value={mediaOverlay.source_labels?.[key] ?? label} onChange={e => {
              const next = { ...mediaOverlay, source_labels: { ...mediaOverlay.source_labels, [key]: e.target.value } }
              setMediaOverlay(next); savePositionsSoon({ media_overlay: next })
            }} className="block w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white" />
          </label>
        ))}
        {[['airing', 'Läuft gerade'], ['running', 'Wird fortgesetzt'], ['ended', 'Abgeschlossen'], ['canceled', 'Abgesetzt']].map(([key, label]) => (
          <label key={key} className="text-gray-400">Status: {key}
            <input value={mediaOverlay.status_labels?.[key] ?? label} onChange={e => {
              const next = { ...mediaOverlay, status_labels: { ...mediaOverlay.status_labels, [key]: e.target.value } }
              setMediaOverlay(next); savePositionsSoon({ media_overlay: next })
            }} className="block w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white" />
          </label>
        ))}
      </div>
      {!Object.values(ratingSources).some(v => v) && (
        <div className="mt-2 p-3 bg-red-900/20 border border-red-700/50 rounded text-sm text-red-300">
          ⚠️ At least one rating source must be selected
        </div>
      )}
    </div>
  )
}
