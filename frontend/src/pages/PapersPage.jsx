import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { BookOpen, Search, Loader2, Map } from 'lucide-react'
import { fetchPapers } from '../api'
import SourceLink from '../components/SourceLink'
import SaveButton from '../components/SaveButton'
import LoadingSpinner from '../components/LoadingSpinner'

const PAGE = 50

/**
 * Full browsable list of every paper in the project — title, authors,
 * journal · year, PMID + DOI, and claim count. Lets a researcher browse the
 * whole corpus, search it, save any paper, and see how many papers/claims the
 * build has produced (progress for a freshly built project).
 */
export default function PapersPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const [term, setTerm] = useState('')   // live input
  const [q, setQ] = useState('')         // submitted query
  const [offset, setOffset] = useState(0)

  // Jump to the workbench map and spotlight the clusters this paper appears in.
  const showOnMap = (p) => {
    if (!p.cluster_ids?.length) return
    navigate(`/projects/${projectId}`, {
      state: { locateClusterIds: p.cluster_ids, locateSource: p.source_id },
    })
  }

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['papers', projectId, q, offset],
    queryFn: () => fetchPapers(projectId, { q, limit: PAGE, offset }),
    enabled: !!projectId,
    placeholderData: keepPreviousData,
  })

  const papers = data?.papers || []
  const total = data?.total ?? 0
  const submit = (e) => { e.preventDefault(); setOffset(0); setQ(term.trim()) }

  return (
    <div className="h-full flex flex-col bg-slate-50">
      {/* Header */}
      <div className="px-6 pt-5 pb-4 border-b border-slate-200 bg-white">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <BookOpen size={17} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-800 leading-none">Papers</h1>
            <p className="text-xs text-slate-400 mt-1">
              {q ? `${total} paper${total === 1 ? '' : 's'} match “${q}”` : `${total} papers in this project`}
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-4 flex items-center gap-2">
          <div className="relative flex-1 max-w-xl">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Search titles and abstracts…"
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50
                         focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white"
            />
          </div>
          <button type="submit"
            className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700">
            Search
          </button>
          {q && (
            <button type="button" onClick={() => { setTerm(''); setQ(''); setOffset(0) }}
              className="px-3 py-2 rounded-lg border border-slate-200 text-slate-500 text-sm hover:bg-slate-50">
              Clear
            </button>
          )}
        </form>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
        ) : papers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-6 border border-dashed border-slate-200 rounded-xl bg-white">
            <BookOpen size={30} className="mb-3 opacity-40" />
            <p className="text-sm font-medium text-slate-500">No papers found</p>
            <p className="text-xs mt-1">{q ? 'Try a different search term.' : 'This project has no ingested papers yet.'}</p>
          </div>
        ) : (
          <ul className="max-w-3xl mx-auto space-y-2">
            {papers.map((p) => (
              <li key={p.source_id} className="card px-4 py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {p.title ? (
                    p.cluster_ids?.length ? (
                      <button
                        onClick={() => showOnMap(p)}
                        title="Show this paper on the cluster map"
                        className="group text-left text-sm font-medium text-slate-800 leading-snug hover:text-blue-700"
                      >
                        {p.title}
                        <Map size={12} className="inline-block ml-1.5 align-baseline text-slate-300 group-hover:text-blue-500" />
                      </button>
                    ) : (
                      <p className="text-sm font-medium text-slate-800 leading-snug">{p.title}</p>
                    )
                  ) : (
                    <p className="text-sm font-medium text-slate-500 font-mono">{p.source_id}</p>
                  )}
                  {p.authors && <p className="mt-0.5 text-xs text-slate-500 leading-snug">{p.authors}</p>}
                  {(p.journal || p.year) && (
                    <p className="mt-0.5 text-[11px] text-slate-400 italic">
                      {[p.journal, p.year].filter(Boolean).join(' · ')}
                    </p>
                  )}
                  <div className="mt-1.5 flex items-center gap-x-2.5 gap-y-1 flex-wrap">
                    <SourceLink id={p.source_id} />
                    {p.doi && <SourceLink id={p.doi} />}
                    {p.claim_count > 0 && (
                      <span className="text-[10px] text-slate-400">
                        {p.claim_count} claim{p.claim_count === 1 ? '' : 's'}
                      </span>
                    )}
                  </div>
                </div>
                <SaveButton source_id={p.source_id} doi={p.doi} title={p.title} added_from="paper_list" showLabel />
              </li>
            ))}
          </ul>
        )}

        {/* Pager */}
        {papers.length > 0 && total > PAGE && (
          <div className="max-w-3xl mx-auto mt-4 flex items-center justify-between text-sm">
            <button
              disabled={offset === 0 || isFetching}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-xs text-slate-400 inline-flex items-center gap-1.5">
              {isFetching && <Loader2 size={12} className="animate-spin" />}
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <button
              disabled={offset + PAGE >= total || isFetching}
              onClick={() => setOffset(offset + PAGE)}
              className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-50"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
