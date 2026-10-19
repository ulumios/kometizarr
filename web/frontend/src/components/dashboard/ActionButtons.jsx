export default function ActionButtons({ selectedLibrary, selectedLibraries, previewLoading, restoreOriginals, previewPosters, planProcessing, startProcessing }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <button
        onClick={restoreOriginals}
        disabled={!selectedLibrary}
        className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
      >
        🔄 Restore
      </button>
      <button
        onClick={previewPosters}
        disabled={!selectedLibrary || previewLoading}
        className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
      >
        {previewLoading ? '⏳ Generating…' : '🔍 Preview'}
      </button>
      <button
        onClick={planProcessing}
        disabled={selectedLibraries.length !== 1}
        title="Zeigt, was ein Lauf rendern, überspringen oder melden würde – ohne etwas zu ändern"
        className="bg-gray-600 hover:bg-gray-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
      >
        📋 Lauf prüfen
      </button>
      <button
        onClick={startProcessing}
        disabled={selectedLibraries.length === 0}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-lg transition"
      >
        {selectedLibraries.length > 1 ? `▶️ Process (${selectedLibraries.length})` : '▶️ Process'}
      </button>
    </div>
  )
}
