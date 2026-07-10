import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchCriteria, updateCriterion, deleteCriterion, api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import Badge from '../components/Badge'
import { Lock, Trash2, Edit3, CheckCircle, ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { SourceList } from '../components/SourceLink'

function CriterionRow({ c, projectId }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const [statement, setStatement] = useState(c.statement)
  const [goldNote, setGoldNote] = useState('')

  const { mutate: save, isPending: isSaving } = useMutation({
    mutationFn: () => updateCriterion(projectId, c.id, { statement }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['criteria', projectId] })
      setEditing(false)
    },
  })

  const { mutate: setGold, isPending: isSettingGold } = useMutation({
    mutationFn: () => api.patch(`/projects/${projectId}/criteria/${c.id}`, { is_gold: true, gold_note: goldNote || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['criteria', projectId] }),
  })

  const { mutate: remove, isPending: isRemoving } = useMutation({
    mutationFn: () => deleteCriterion(projectId, c.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['criteria', projectId] }),
  })

  const isInclusion = c.criterion_type === 'inclusion'
  const borderColor = isInclusion ? 'border-l-emerald-400' : 'border-l-red-400'

  return (
    <div className={`card border-l-4 ${borderColor} overflow-hidden`}>
      <div className="px-4 py-3">
        <div className="flex items-start gap-3">
          <button onClick={() => setOpen((o) => !o)} className="mt-0.5 shrink-0">
            {open ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge color={isInclusion ? 'green' : 'red'}>
                {c.criterion_type.toUpperCase()}
              </Badge>
              {c.is_gold && (
                <Badge color="amber"><Lock size={9} className="inline mr-0.5" />Gold</Badge>
              )}
              {c.confidence > 0 && (
                <span className="text-xs text-slate-400">{Math.round(c.confidence * 100)}% confidence</span>
              )}
            </div>

            {editing ? (
              <textarea
                className="textarea text-sm mt-2"
                rows={3}
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
              />
            ) : (
              <p className="text-sm text-slate-800 mt-1 leading-snug">{c.statement}</p>
            )}
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => setEditing((e) => !e)}
              className="p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              title="Edit"
            >
              <Edit3 size={13} />
            </button>
            <button
              onClick={() => remove()}
              disabled={isRemoving}
              className="p-1.5 rounded hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors"
              title="Delete"
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>

        {editing && (
          <div className="flex gap-2 mt-2 ml-5">
            <button className="btn-primary text-xs" onClick={() => save()} disabled={isSaving}>
              {isSaving ? <LoadingSpinner size="sm" /> : <CheckCircle size={12} />}
              Save
            </button>
            <button className="btn-secondary text-xs" onClick={() => { setEditing(false); setStatement(c.statement) }}>
              Cancel
            </button>
          </div>
        )}
      </div>

      {open && (
        <div className="border-t border-slate-100 px-4 py-3 bg-slate-50 space-y-2">
          {c.rationale && (
            <p className="text-xs text-slate-600 leading-relaxed"><strong>Rationale:</strong> {c.rationale}</p>
          )}
          {c.source_ids?.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 font-medium mb-1">Sources</p>
              <SourceList ids={c.source_ids} short />
            </div>
          )}
          {c.gold_note && (
            <p className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">{c.gold_note}</p>
          )}

          {!c.is_gold && (
            <div className="flex items-center gap-2 pt-1">
              <input
                className="input text-xs flex-1"
                placeholder="Gold note (optional)"
                value={goldNote}
                onChange={(e) => setGoldNote(e.target.value)}
              />
              <button
                className="btn-secondary text-xs whitespace-nowrap"
                onClick={() => setGold()}
                disabled={isSettingGold}
              >
                <Lock size={11} /> Set Gold
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function SteeringPage() {
  const { id: projectId } = useParams()
  const qc = useQueryClient()
  const [showSampleForm, setShowSampleForm] = useState(false)
  const [sample, setSample] = useState({ text_sample: '', label: 'inclusion', note: '', is_hard_constraint: true })
  const [goldLabels, setGoldLabels] = useState(null)

  const { data: criteria = [], isLoading } = useQuery({
    queryKey: ['criteria', projectId],
    queryFn: () => fetchCriteria(projectId),
  })

  const { mutate: submitSample, isPending: isSubmitting } = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/gold-labels`, sample),
    onSuccess: () => {
      setSample({ text_sample: '', label: 'inclusion', note: '', is_hard_constraint: true })
      setShowSampleForm(false)
      // reload gold labels
      api.get(`/projects/${projectId}/gold-labels`).then(setGoldLabels)
    },
  })

  const inclusion = criteria.filter((c) => c.criterion_type === 'inclusion')
  const exclusion = criteria.filter((c) => c.criterion_type === 'exclusion')

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-slate-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Criteria Steering</h1>
          <p className="text-sm text-slate-500">
            Edit criteria, set Gold Values, and label text samples
          </p>
        </div>
        <button className="btn-secondary text-xs" onClick={() => setShowSampleForm((o) => !o)}>
          <Plus size={13} /> Label Sample
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {/* Sample form */}
        {showSampleForm && (
          <div className="card p-5">
            <h3 className="text-sm font-semibold text-slate-800 mb-4">Label a New Text Sample</h3>
            <div className="space-y-3">
              <div>
                <label className="label">Text Sample *</label>
                <textarea
                  className="textarea"
                  rows={4}
                  placeholder="Paste a text sample to label as a Gold Value…"
                  value={sample.text_sample}
                  onChange={(e) => setSample((s) => ({ ...s, text_sample: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Label</label>
                  <select
                    className="input"
                    value={sample.label}
                    onChange={(e) => setSample((s) => ({ ...s, label: e.target.value }))}
                  >
                    <option value="inclusion">Inclusion</option>
                    <option value="exclusion">Exclusion</option>
                    <option value="ambiguous">Ambiguous</option>
                  </select>
                </div>
                <div>
                  <label className="label">Analyst Note</label>
                  <input
                    className="input"
                    placeholder="Optional"
                    value={sample.note}
                    onChange={(e) => setSample((s) => ({ ...s, note: e.target.value }))}
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sample.is_hard_constraint}
                  onChange={(e) => setSample((s) => ({ ...s, is_hard_constraint: e.target.checked }))}
                  className="rounded border-slate-300"
                />
                <span className="text-sm text-slate-700">Hard constraint (agents cannot override)</span>
              </label>
              <div className="flex gap-2">
                <button className="btn-primary text-xs" onClick={() => submitSample()} disabled={isSubmitting || !sample.text_sample.trim()}>
                  {isSubmitting ? <LoadingSpinner size="sm" /> : <CheckCircle size={12} />}
                  Submit Label
                </button>
                <button className="btn-secondary text-xs" onClick={() => setShowSampleForm(false)}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-10"><LoadingSpinner label="Loading criteria…" /></div>
        ) : criteria.length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <p className="font-medium">No criteria yet</p>
            <p className="text-sm mt-1">Run analysis on the Research page to extract criteria</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className="section-title text-emerald-600 mb-3">Inclusion ({inclusion.length})</p>
              <div className="space-y-2">
                {inclusion.map((c) => (
                  <CriterionRow key={c.id} c={c} projectId={projectId} />
                ))}
              </div>
            </div>
            <div>
              <p className="section-title text-red-500 mb-3">Exclusion ({exclusion.length})</p>
              <div className="space-y-2">
                {exclusion.map((c) => (
                  <CriterionRow key={c.id} c={c} projectId={projectId} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
