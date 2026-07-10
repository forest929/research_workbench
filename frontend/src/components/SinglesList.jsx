import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchSingleClaims } from '../api'
import { EvidenceItem } from './ConversationPanel'
import LoadingSpinner from './LoadingSpinner'
import { Search, FileText, Loader2 } from 'lucide-react'

const VERDICTS = [
  { key: '', label: 'All verdicts' },
  { key: 'supports', label: 'Supports' },
  { key: 'partially_supports', label: 'Partially supports' },
  { key: 'contradicts', label: 'Contradicts' },
  { key: 'inconclusive', label: 'Inconclusive' },
]
const PAGE = 30

/**
 * Browser for single-paper claims — the 15k+ individual verified claims that
 * didn't converge with others into a multi-source cluster. Searchable and
 * filterable; ranked strongest-first by the same calibrated evidence score.
 */
export default function SinglesList({ projectId, diseases = [] }) {
  const [q, setQ] = useState('')
  const [disease, setDisease] = useState('')
  const [verdict, setVerdict] = useState('')
  const [page, setPage] = useState(0)

  // Reset to first page when a filter changes.
  const filterKey = `${q}|${disease}|${verdict}`
  const [lastKey, setLastKey] = useState(filterKey)
  if (filterKey !== lastKey) { setLastKey(filterKey); setPage(0) }

  const { data, isFetching } = useQuery({
    queryKey: ['singleClaims', projectId, q, disease, verdict, page],
    queryFn: () => fetchSingleClaims(projectId, { q, disease, verdict, limit: PAGE, offset: page * PAGE }),
    placeholderData: keepPreviousData,
  })

  const claims = data?.claims || []
  const total = data?.total ?? 0
  const maxPage = Math.max(0, Math.ceil(total / PAGE) - 1)

  return (
    <div className="h-full flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden">
      {/* Filters */}
      <div className="px-4 py-3 border-b border-slate-100 flex items-end gap-2 flex-wrap shrink-0">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search claims (drug, finding, biomarker…)"
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50
                       focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white"
          />
        </div>
        <select
          value={disease} onChange={(e) => setDisease(e.target.value)}
          className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-400"
        >
          <option value="">All diseases</option>
          {diseases.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
        </select>
        <select
          value={verdict} onChange={(e) => setVerdict(e.target.value)}
          className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-400"
        >
          {VERDICTS.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
        </select>
      </div>

      {/* Count + pager */}
      <div className="px-4 py-2 border-b border-slate-50 flex items-center justify-between text-xs text-slate-500 shrink-0">
        <span className="flex items-center gap-1.5">
          <FileText size={13} className="text-slate-400" />
          {total.toLocaleString()} single-paper claim{total === 1 ? '' : 's'}
          {isFetching && <Loader2 size={12} className="animate-spin ml-1" />}
        </span>
        {total > PAGE && (
          <span className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50">Prev</button>
            <span>{page + 1} / {maxPage + 1}</span>
            <button disabled={page >= maxPage} onClick={() => setPage((p) => p + 1)}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:bg-slate-50">Next</button>
          </span>
        )}
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-2">
        {!data ? (
          <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
        ) : claims.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 text-sm">
            <FileText size={26} className="mb-2 opacity-40" />
            No single-paper claims match these filters.
          </div>
        ) : (
          claims.map((m) => <EvidenceItem key={m.id} m={m} />)
        )}
      </div>
    </div>
  )
}
