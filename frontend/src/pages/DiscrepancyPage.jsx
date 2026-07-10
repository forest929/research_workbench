import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import Badge from '../components/Badge'
import { GitCompare, ChevronDown, ChevronRight, Search } from 'lucide-react'

const FRICTION_CONFIG = {
  wording: { color: 'blue', label: 'Wording' },
  evidence_interpretation: { color: 'purple', label: 'Evidence Interpretation' },
  scope_boundary: { color: 'amber', label: 'Scope Boundary' },
  contradictory: { color: 'red', label: 'Contradictory' },
}

function FrictionPoint({ fp, labelA, labelB }) {
  const [open, setOpen] = useState(false)
  const conf = FRICTION_CONFIG[fp.friction_type] || { color: 'slate', label: fp.friction_type }
  return (
    <div className="card overflow-hidden">
      <button
        className="w-full px-4 py-3 text-left flex items-center gap-3 hover:bg-slate-50 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={14} className="text-slate-400 shrink-0" /> : <ChevronRight size={14} className="text-slate-400 shrink-0" />}
        <Badge color={conf.color}>{conf.label}</Badge>
        <span className="text-sm text-slate-800 flex-1">{fp.summary}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 grid grid-cols-2 gap-px bg-slate-100">
          <div className="bg-white px-4 py-3">
            <p className="text-xs font-semibold text-slate-500 mb-1">{labelA}</p>
            <p className="text-sm text-slate-700 leading-relaxed">{fp.position_a || '—'}</p>
          </div>
          <div className="bg-white px-4 py-3">
            <p className="text-xs font-semibold text-slate-500 mb-1">{labelB}</p>
            <p className="text-sm text-slate-700 leading-relaxed">{fp.position_b || '—'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default function DiscrepancyPage() {
  const { id: projectId } = useParams()
  const [labelA, setLabelA] = useState('Team A')
  const [labelB, setLabelB] = useState('Team B')
  const [defA, setDefA] = useState('')
  const [defB, setDefB] = useState('')
  const [result, setResult] = useState(null)

  const { mutate, isPending, error } = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/discrepancy`, {
      definition_a: defA,
      definition_b: defB,
      label_a: labelA,
      label_b: labelB,
    }),
    onSuccess: (data) => setResult(data),
  })

  const overlap = result?.semantic_overlap
  const frictionPoints = result?.friction_points || []

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-slate-200 bg-white shrink-0">
        <h1 className="text-lg font-semibold text-slate-900">Discrepancy Analyzer</h1>
        <p className="text-sm text-slate-500">
          Compare two competing scope definitions to find semantic friction
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5 max-w-5xl">
        {/* Input panel */}
        <div className="grid grid-cols-2 gap-4">
          <div className="card p-4 space-y-3">
            <input
              className="input text-sm font-medium"
              placeholder="Team A label"
              value={labelA}
              onChange={(e) => setLabelA(e.target.value)}
            />
            <textarea
              className="textarea"
              rows={8}
              placeholder={`${labelA}'s scope definition…`}
              value={defA}
              onChange={(e) => setDefA(e.target.value)}
            />
          </div>
          <div className="card p-4 space-y-3">
            <input
              className="input text-sm font-medium"
              placeholder="Team B label"
              value={labelB}
              onChange={(e) => setLabelB(e.target.value)}
            />
            <textarea
              className="textarea"
              rows={8}
              placeholder={`${labelB}'s scope definition…`}
              value={defB}
              onChange={(e) => setDefB(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {error.message}
          </div>
        )}

        <button
          className="btn-primary"
          onClick={() => mutate()}
          disabled={isPending || !defA.trim() || !defB.trim()}
        >
          {isPending ? <><LoadingSpinner size="sm" /> Analyzing…</> : <><Search size={14} /> Analyze Discrepancy</>}
        </button>

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {overlap !== undefined && (
              <div className="card px-5 py-4 flex items-center gap-4">
                <div>
                  <p className="text-2xl font-bold text-slate-900">{(overlap * 100).toFixed(0)}%</p>
                  <p className="text-xs text-slate-500">Semantic overlap</p>
                </div>
                <div className="flex-1">
                  <div className="bg-slate-100 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full transition-all ${overlap > 0.7 ? 'bg-emerald-500' : overlap > 0.4 ? 'bg-amber-400' : 'bg-red-500'}`}
                      style={{ width: `${Math.round(overlap * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-400 mt-1">Cosine similarity of scope embeddings</p>
                </div>
                <div className="flex items-center gap-1.5">
                  <GitCompare size={16} className="text-slate-400" />
                  <span className="text-sm font-medium text-slate-700">
                    {frictionPoints.length} friction point{frictionPoints.length !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>
            )}

            {frictionPoints.length > 0 && (
              <div className="space-y-2">
                <p className="section-title">Friction Points</p>
                {frictionPoints.map((fp, i) => (
                  <FrictionPoint key={i} fp={fp} labelA={labelA} labelB={labelB} />
                ))}
              </div>
            )}

            {result.recommendation && (
              <div className="card p-4">
                <p className="text-xs font-semibold text-slate-600 mb-2 uppercase tracking-wide">Recommendation</p>
                <p className="text-sm text-slate-700 leading-relaxed">{result.recommendation}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
