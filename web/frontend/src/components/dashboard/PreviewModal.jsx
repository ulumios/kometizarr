// Preview Modal — rendered outside the main panel so it overlays everything
export default function PreviewModal({ results, loading, onClose }) {
  if (results === null) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80" onClick={onClose}>
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-4 sm:p-6 max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-white">🔍 Preview — 3 random items</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">✕</button>
        </div>

        {loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12">Fetching ratings & rendering posters…</div>
        )}

        {!loading && results.length === 0 && (
          <div className="text-center text-gray-400 py-12">No results — library may have no rated items with matching sources.</div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          {results.map((item, i) => (
            <div key={i} className="flex flex-col items-center gap-2 min-w-0">
              <img
                src={`data:image/jpeg;base64,${item.image}`}
                alt={item.title}
                className="rounded-lg w-full object-cover shadow-lg"
              />
              <div className="text-center">
                <div className="text-sm font-medium text-white truncate w-full">{item.title} {item.year && <span className="text-gray-400">({item.year})</span>}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {Object.entries(item.ratings).map(([k, v]) => `${k.toUpperCase()}: ${v}`).join(' · ')}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
