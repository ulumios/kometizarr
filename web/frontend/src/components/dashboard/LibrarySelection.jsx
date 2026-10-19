export default function LibrarySelection({ libraries, selectedLibraries, setSelectedLibraries, setSelectedLibrary, toggleLibrarySelection, includeEpisodes }) {
  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Select Libraries</h2>
        {libraries.length > 1 && (
          <button
            onClick={() => {
              const allSelected = selectedLibraries.length === libraries.length
              setSelectedLibraries(allSelected ? [] : libraries.map(l => l.name))
              setSelectedLibrary(allSelected ? null : libraries[0])
            }}
            className="text-xs text-gray-400 hover:text-gray-200 transition"
          >
            {selectedLibraries.length === libraries.length ? 'Deselect all' : 'Select all'}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {libraries.map((lib) => {
          const isSelected = selectedLibraries.includes(lib.name)
          return (
            <button
              key={lib.name}
              onClick={() => toggleLibrarySelection(lib)}
              className={`p-4 rounded-lg border-2 transition relative text-left ${
                isSelected
                  ? 'border-blue-500 bg-blue-900/20'
                  : 'border-gray-700 hover:border-gray-600'
              }`}
            >
              {/* Checkbox indicator */}
              <div className={`absolute top-3 right-3 w-5 h-5 rounded border-2 flex items-center justify-center text-xs font-bold transition ${
                isSelected ? 'border-blue-500 bg-blue-500 text-white' : 'border-gray-500'
              }`}>
                {isSelected && '✓'}
              </div>
              <div className="font-semibold pr-7">{lib.name}</div>
              <div className="text-sm text-gray-400 mt-1">
                {lib.type === 'movie' ? `🎬 ${lib.count} Filme` :
                  `📺 ${lib.count} Serien${includeEpisodes ? ` + ${lib.episode_count || 0} Episoden` : ''}`}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
