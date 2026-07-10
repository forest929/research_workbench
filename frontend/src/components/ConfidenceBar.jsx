export default function ConfidenceBar({ label, confidence }) {
  const isInclude = label === 'include'
  const pct = Math.round((confidence ?? 0.5) * 100)
  const color = isInclude ? 'bg-emerald-500' : 'bg-red-500'
  const textColor = isInclude ? 'text-emerald-700' : 'text-red-700'
  const bgColor = isInclude ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'

  return (
    <div className={`rounded-xl border px-4 py-3 ${bgColor}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{isInclude ? '✅' : '❌'}</span>
          <span className={`font-semibold text-base ${textColor}`}>
            {label?.toUpperCase() ?? 'UNKNOWN'}
          </span>
        </div>
        <span className="text-sm font-medium text-slate-600">{pct}% confidence</span>
      </div>
      <div className="bg-white/60 rounded-full h-2">
        <div
          className={`${color} h-2 rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
