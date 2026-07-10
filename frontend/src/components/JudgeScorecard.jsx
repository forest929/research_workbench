import Badge from './Badge'

const DIMS = [
  { key: 'faithfulness', label: 'Faithfulness' },
  { key: 'integrity', label: 'Integrity' },
  { key: 'citation_accuracy', label: 'Citation accuracy' },
  { key: 'uncertainty', label: 'Uncertainty flagged' },
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

  const overall = verdict.overall ?? verdict.overall_score
  const v = verdict.verdict?.toLowerCase()
  const verdictColor = v === 'pass' ? 'green' : v === 'death_spiral' ? 'red' : 'amber'

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">LLM-as-Judge</h3>
        <div className="flex items-center gap-2">
          {overall !== undefined && (
            <span className="text-lg font-bold text-slate-900">{Number(overall).toFixed(1)}<span className="text-xs font-normal text-slate-400">/5</span></span>
          )}
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
