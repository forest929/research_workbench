import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Plus, Trash2, Tag } from 'lucide-react'
import { updateDiseaseVocab } from '../api'

const slug = (s) =>
  s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

/**
 * Per-project disease vocabulary editor. The vocabulary drives cluster disease
 * tags + the disease filter; it is project-scoped, so a project on any topic
 * defines its own terms instead of inheriting the women's-cancer defaults.
 */
export default function DiseaseVocabEditor({ projectId, vocab, onClose }) {
  const qc = useQueryClient()
  // entries: [{ key, label, keywords: "a, b" }]
  const [entries, setEntries] = useState(() =>
    Object.entries(vocab || {}).map(([key, m]) => ({
      key,
      label: m.label || key,
      keywords: (m.keywords || []).join(', '),
    }))
  )
  const [label, setLabel] = useState('')
  const [keywords, setKeywords] = useState('')

  const save = useMutation({
    mutationFn: (v) => updateDiseaseVocab(projectId, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workbenchOptions', projectId] })
      qc.invalidateQueries({ queryKey: ['clusters', projectId] })
      onClose()
    },
  })

  function addEntry() {
    const lbl = label.trim()
    const kws = keywords.split(',').map((k) => k.trim().toLowerCase()).filter(Boolean)
    if (!lbl || kws.length === 0) return
    const key = slug(lbl) || `d${entries.length + 1}`
    if (entries.some((e) => e.key === key)) return
    setEntries([...entries, { key, label: lbl, keywords: kws.join(', ') }])
    setLabel('')
    setKeywords('')
  }

  function handleSave() {
    const v = {}
    for (const e of entries) {
      const kws = e.keywords.split(',').map((k) => k.trim().toLowerCase()).filter(Boolean)
      if (e.label.trim() && kws.length) v[e.key] = { label: e.label.trim(), keywords: kws }
    }
    save.mutate(v)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-white rounded-xl shadow-xl border border-slate-200 flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <Tag size={16} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-slate-800">Disease vocabulary</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded text-slate-400 hover:bg-slate-100">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 overflow-y-auto">
          <p className="text-xs text-slate-500 mb-3">
            Terms used to tag clusters and power the disease filter for this project.
            Each disease matches its keywords against claim population/outcome text.
          </p>

          {entries.length === 0 ? (
            <p className="text-xs text-slate-400 italic mb-3">
              No diseases configured — the disease filter is hidden until you add one.
            </p>
          ) : (
            <ul className="space-y-1.5 mb-4">
              {entries.map((e, i) => (
                <li key={e.key} className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-700">{e.label}</p>
                    <p className="text-[11px] text-slate-400 truncate">{e.keywords}</p>
                  </div>
                  <button
                    onClick={() => setEntries(entries.filter((_, j) => j !== i))}
                    className="p-1 rounded text-slate-400 hover:text-red-600 hover:bg-red-50"
                    title="Remove"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Add form */}
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Disease label (e.g. Breast cancer)"
              className="w-full text-sm rounded-lg border border-slate-200 px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <input
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addEntry()}
              placeholder="Match keywords, comma-separated (e.g. breast, mammary)"
              className="w-full text-sm rounded-lg border border-slate-200 px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <button
              onClick={addEntry}
              disabled={!label.trim() || !keywords.trim()}
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-40"
            >
              <Plus size={13} /> Add disease
            </button>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-100">
          {save.isError && (
            <span className="text-xs text-amber-600 mr-auto">{String(save.error?.message || save.error)}</span>
          )}
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={save.isPending}
            className="px-3.5 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {save.isPending ? 'Saving…' : 'Save vocabulary'}
          </button>
        </div>
      </div>
    </div>
  )
}
