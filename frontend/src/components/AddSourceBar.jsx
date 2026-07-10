import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { addSource, fetchUserSources } from '../api'
import { Plus, Loader2, CheckCircle2, AlertCircle, FlaskConical, Crosshair } from 'lucide-react'

const ACTIVE = ['pending', 'fetching', 'extracting', 'embedding', 'clustering']

function StatusChip({ s, onLocate }) {
  const active = ACTIVE.includes(s.status)
  const failed = s.status === 'failed'
  const Icon = active ? Loader2 : failed ? AlertCircle : CheckCircle2
  const color = active ? 'text-blue-600' : failed ? 'text-amber-600' : 'text-emerald-600'
  const canLocate = (s.status === 'existing' || s.status === 'done') && s.cluster_ids?.length > 0
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <Icon size={13} className={`${color} ${active ? 'animate-spin' : ''} shrink-0`} />
      <span className="text-slate-600 truncate max-w-[260px]" title={s.title || s.doi}>
        {s.title || s.doi}
      </span>
      <span className={`${color} shrink-0`}>{s.message}</span>
      {canLocate && (
        <button
          onClick={() => onLocate(s.cluster_ids)}
          className="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 hover:bg-amber-100 font-medium"
        >
          <Crosshair size={11} /> Locate on map
        </button>
      )}
    </div>
  )
}

/**
 * Add a source by DOI. Fires the background pipeline (resolve → extract → embed →
 * cluster) and polls status; when a job finishes it refreshes the map so the
 * user-touched cluster appears with its distinct bubble style.
 */
export default function AddSourceBar({ projectId, onLocate }) {
  const qc = useQueryClient()
  const [doi, setDoi] = useState('')
  const prevActive = useRef(0)

  const { data } = useQuery({
    queryKey: ['userSources', projectId],
    queryFn: () => fetchUserSources(projectId),
    refetchInterval: (query) => {
      const rows = query.state.data?.sources || []
      return rows.some((s) => ACTIVE.includes(s.status)) ? 2500 : false
    },
  })
  const sources = data?.sources || []

  // When active jobs drain to zero, a job just finished → refresh the map data
  // and auto-locate the source that just landed.
  useEffect(() => {
    const active = sources.filter((s) => ACTIVE.includes(s.status)).length
    if (prevActive.current > 0 && active === 0) {
      qc.invalidateQueries({ queryKey: ['clusters', projectId] })
      qc.invalidateQueries({ queryKey: ['clusterStats', projectId] })
      qc.invalidateQueries({ queryKey: ['singleClaims', projectId] })
      const latest = sources.find((s) => (s.status === 'done' || s.status === 'existing') && s.cluster_ids?.length)
      if (latest) onLocate?.(latest.cluster_ids)
    }
    prevActive.current = active
  }, [sources, qc, projectId, onLocate])

  const add = useMutation({
    mutationFn: (d) => addSource(projectId, d),
    onSuccess: () => { setDoi(''); qc.invalidateQueries({ queryKey: ['userSources', projectId] }) },
  })

  function submit(e) {
    e.preventDefault()
    const d = doi.trim()
    if (d) add.mutate(d)
  }

  const latest = sources[0]

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <form onSubmit={submit} className="flex items-center gap-2">
        <div className="relative">
          <FlaskConical size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-violet-400" />
          <input
            value={doi}
            onChange={(e) => setDoi(e.target.value)}
            placeholder="Add a source by DOI (e.g. 10.1056/NEJMoa2203690)"
            className="w-[340px] pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50
                       focus:outline-none focus:ring-2 focus:ring-violet-400 focus:bg-white"
          />
        </div>
        <button
          type="submit"
          disabled={add.isPending || !doi.trim()}
          className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium
                     hover:bg-violet-700 disabled:opacity-50 flex items-center gap-1.5"
        >
          <Plus size={14} /> Add
        </button>
      </form>
      {add.isError && <span className="text-xs text-amber-600">{String(add.error?.message || add.error)}</span>}
      {latest && <StatusChip s={latest} onLocate={onLocate} />}
    </div>
  )
}
