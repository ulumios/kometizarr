export default function LibraryStats({ stats }) {
  if (!stats) return null
  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h2 className="text-xl font-semibold mb-4">Library Statistics</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-900 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Total Items</div>
          <div className="text-3xl font-bold mt-1">{stats.total_items}</div>
        </div>
        <div className="bg-gray-900 rounded-lg p-4">
          <div className="text-gray-400 text-sm">With Backups</div>
          <div className="text-3xl font-bold mt-1 text-green-400">
            {stats.processed_items}
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Backup Coverage</div>
          <div className="text-3xl font-bold mt-1 text-blue-400">
            {stats.success_rate}%
          </div>
        </div>
      </div>
    </div>
  )
}
