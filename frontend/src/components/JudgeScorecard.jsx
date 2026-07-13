import Badge from './Badge'

const DIMS = [
  { key: 'faithfulness', label: 'Faithfulness' },
  { key: 'citation_accuracy', label: 'Citation accuracy' },
  { key: 'relevance', label: 'Relevance' },
  { key: 'completeness', label: 'Completeness' },
]

function ScoreBar({ score, max = 5 }) {
  const pct = Math.round((score / max) * 100)
  const color = score >= 4 ? 'bg-emerald-500' : score >= 3 ? 'bg-amber-400' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-100 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-slate-600 w-6 text-right">{score}/5</span>
    </div>
  )
}

export default function JudgeScorecard({ verdict }) {
  if (!verdict) return null

  // Consistent headline everywhere: the total across the four dimensions, out of
  // 20 (4 × 5). Computed from the dimension scores, not the model's free-form
  // "overall", so it always matches the bars below.
  const total = DIMS.reduce((s, { key }) => s + (Number(verdict[key] ?? verdict[`${key}_score`]) || 0), 0)
  const maxTotal = DIMS.length * 5
  const v = verdict.verdict?.toLowerCase()
  const verdictColor = v === 'pass' ? 'green' : (v === 'fail' || v === 'death_spiral') ? 'red' : 'amber'

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">LLM-as-Judge</h3>
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-slate-900">{total}<span className="text-xs font-normal text-slate-400">/{maxTotal}</span></span>
          {v && <Badge color={verdictColor}>{v.toUpperCase()}</Badge>}
        </div>
      </div>

      <div className="space-y-2">
        {DIMS.map(({ key, label }) => {
          const score = verdict[key] ?? verdict[`${key}_score`]
          const rationale = verdict[`${key}_rationale`] || verdict[`${key}_reason`]
          if (score === undefined) return null
          return (
            <div key={key}>
              <div className="flex justify-between items-center mb-0.5">
                <span className="text-xs text-slate-600">{label}</span>
              </div>
              <ScoreBar score={Number(score)} />
              {rationale && (
                <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{rationale}</p>
              )}
            </div>
          )
        })}
      </div>

      {verdict.summary && (
        <p className="text-xs text-slate-600 bg-slate-50 rounded-lg px-3 py-2 leading-relaxed border border-slate-100">
          {verdict.summary}
        </p>
      )}
    </div>
  )
}
