export default function DesignScope({ libraries, design }) {
  const { designScope, profiles, changeDesignScope } = design
  return (
    <div className="bg-gray-900 rounded-lg p-4 mb-5 space-y-2">
      <label className="text-sm font-medium block" htmlFor="design-scope">Design gilt für</label>
      <div className="flex flex-wrap gap-2 items-center">
        <select id="design-scope" value={designScope} onChange={e => changeDesignScope(e.target.value)}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm">
          <option value="">Alle Bibliotheken (Standard)</option>
          {libraries.map(lib => <option key={lib.name} value={lib.name}>
            {lib.name}{profiles[lib.name] ? ' – eigenes Design' : ''}</option>)}
        </select>
        {designScope && profiles[designScope] &&
          <button onClick={() => changeDesignScope(designScope, true)}
            className="text-xs bg-gray-700 hover:bg-gray-600 rounded px-2 py-1">Eigenes Design entfernen</button>}
      </div>
      <p className="text-xs text-gray-400">
        {designScope
          ? `Änderungen gelten nur für „${designScope}“. Nicht geänderte Einstellungen kommen vom Standard.`
          : 'Änderungen gelten für alle Bibliotheken ohne eigenes Design.'}
      </p>
    </div>
  )
}
