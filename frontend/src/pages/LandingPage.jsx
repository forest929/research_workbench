import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchProjects, createProject, triggerSearch, deleteProject } from '../api'
import { Search, ArrowRight, Trash2, Upload, Loader2 } from 'lucide-react'

function fmt(v) {
  if (!v) return null
  const d = new Date(String(v).replace(' ', 'T') + (String(v).includes('Z') ? '' : 'Z'))
  return isNaN(d) ? null : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export default function LandingPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)

  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: fetchProjects })
  const del = useMutation({
    mutationFn: (id) => deleteProject(id),
    // The server delete cascades a lot of rows and can take several seconds.
    // Optimistically drop the row so it disappears immediately, and roll back
    // if the request fails.
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['projects'] })
      const previous = qc.getQueryData(['projects'])
      qc.setQueryData(['projects'], (old = []) => old.filter((p) => p.id !== id))
      return { previous }
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(['projects'], ctx.previous)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })

  async function runSearch(e) {
    e.preventDefault()
    const query = q.trim()
    if (!query || busy) return
    setBusy(true)
    try {
      const name = query.length > 70 ? query.slice(0, 70) + '…' : query
      const project = await createProject({ name, description: '', scope_statement: query })
      qc.invalidateQueries({ queryKey: ['projects'] })
      await triggerSearch(project.id, { query, sources: ['pubmed'], max_records: 30 })
      navigate(`/projects/${project.id}`)
    } catch {
      setBusy(false)
    }
  }

  const onDelete = (e, p) => {
    e.stopPropagation()
    if (window.confirm(`Delete “${p.name}”? This can't be undone.`)) del.mutate(p.id)
  }

  return (
    <div className="min-h-screen flex flex-col items-center px-4 bg-gradient-to-b from-[#EAEEF3] via-[#F1F4F8] to-[#F5F7FA]">
      <div className="w-full max-w-xl flex flex-col items-center pt-[20vh] pb-16">
        {/* Wordmark */}
        <div className="flex items-center gap-2.5 mb-9">
          <span className="h-7 w-7 rounded-md bg-slate-900 text-white grid place-items-center font-display text-sm leading-none">R</span>
          <span className="font-display text-lg text-slate-900">Research Workbench</span>
        </div>

        {/* Hero + search */}
        <h1 className="font-display text-[32px] md:text-4xl text-slate-900 text-center leading-tight mb-8">
          What does the evidence say?
        </h1>

        <form onSubmit={runSearch} className="w-full">
          <div className="relative">
            <Search size={19} className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ask about a drug, disease, or outcome…"
              className="w-full h-16 pl-14 pr-28 rounded-2xl bg-white/90 text-[15px] border-0
                         shadow-[0_1px_3px_rgba(15,23,42,0.04),0_8px_28px_-6px_rgba(15,23,42,0.12)]
                         focus:outline-none placeholder:text-slate-400
                         transition-shadow focus:shadow-[0_0_0_4px_rgba(37,99,235,0.10),0_10px_34px_-6px_rgba(37,99,235,0.22)]"
            />
            <button
              type="submit"
              disabled={!q.trim() || busy}
              className="absolute right-2.5 top-2.5 h-11 px-4 rounded-xl bg-blue-600 text-white text-sm font-medium
                         hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5 transition-colors"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <>Search <ArrowRight size={15} /></>}
            </button>
          </div>
        </form>
        <Link to="/new" className="mt-3.5 inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600">
          <Upload size={12} /> Import files or DOIs instead
        </Link>

        {/* Existing reviews — quiet rows */}
        {projects.length > 0 && (
          <div className="w-full mt-14">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400 mb-1 px-3">Your reviews</p>
            <ul>
              {projects.map((p) => (
                <li
                  key={p.id}
                  onClick={() => navigate(`/projects/${p.id}`)}
                  className="group cursor-pointer rounded-xl px-3 py-2.5 flex items-center gap-3 hover:bg-white/70 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-800 group-hover:text-blue-700 truncate">{p.name}</p>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {fmt(p.created_at) && <>Created {fmt(p.created_at)}</>}
                      {fmt(p.updated_at) && p.updated_at !== p.created_at && <> · Edited {fmt(p.updated_at)}</>}
                    </p>
                  </div>
                  <button onClick={(e) => onDelete(e, p)} title="Delete"
                    className="shrink-0 p-1.5 rounded-lg text-slate-300 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all">
                    <Trash2 size={14} />
                  </button>
                  <ArrowRight size={15} className="shrink-0 text-slate-300 group-hover:text-blue-500" />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
