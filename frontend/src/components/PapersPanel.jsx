import { useState, useEffect } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Search, FileText, Loader2, X } from 'lucide-react'
import { fetchPapers, fetchPaper } from '../api'
import SourceLink from './SourceLink'
import SaveButton from './SaveButton'

const PAGE = 50

export function flashEl(el) {
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('ring-2', 'ring-blue-400')
  setTimeout(() => el.classList.remove('ring-2', 'ring-blue-400'), 1400)
}

function PaperRow({ p, onLocate }) {
  return (
    <div id={`paper-${p.source_id}`} className="rounded-lg px-2.5 py-2 hover:bg-slate-50 group scroll-mt-2 transition-shadow duration-300">
      {(p.journal || p.year) && (
        <p className="text-[10px] text-slate-400 italic mb-0.5 line-clamp-1">{[p.journal, p.year].filter(Boolean).join(' · ')}</p>
      )}
      {p.title && p.cluster_ids?.length ? (
        <button onClick={() => onLocate?.(p.cluster_ids, p.source_id)} title="Show on the map"
          className="text-left text-[13px] font-medium leading-snug text-slate-800 hover:text-blue-700 line-clamp-2">{p.title}</button>
      ) : (
        <p className="text-[13px] font-medium leading-snug text-slate-800 line-clamp-2">{p.title || p.source_id}</p>
      )}
      {p.authors && <p className="mt-0.5 text-[11px] text-slate-500 line-clamp-1">{p.authors}</p>}
      <div className="mt-1 flex items-center gap-x-2 gap-y-0.5 flex-wrap">
        <SourceLink id={p.source_id} />
        {p.doi && <SourceLink id={p.doi} />}
        <div className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
          <SaveButton source_id={p.source_id} doi={p.doi} title={p.title} added_from="paper_list" />
        </div>
      </div>
    </div>
  )
}

/** Left column: the papers behind this review. Search, browse (infinite scroll),
 *  save, and click a title to spotlight the paper on the map. */
export default function PapersPanel({ projectId, onLocate }) {
  const [term, setTerm] = useState('')
  const [q, setQ] = useState('')

  // Debounce the input into the query so the list filters as you type and,
  // crucially, restores the full list the moment the field is cleared.
  useEffect(() => {
    const id = setTimeout(() => setQ(term.trim()), 250)
    return () => clearTimeout(id)
  }, [term])

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['papers', projectId, q],
    queryFn: ({ pageParam = 0 }) => fetchPapers(projectId, { q, limit: PAGE, offset: pageParam }),
    enabled: !!projectId,
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + (p.papers?.length || 0), 0)
      return loaded < (last.total || 0) ? loaded : undefined
    },
  })
  const papers = data?.pages.flatMap((p) => p.papers) || []
  const total = data?.pages[0]?.total ?? 0

  // Reveal a cited paper (from a citation click): scroll+flash if it's loaded,
  // else fetch it and pin it at the top of the list, highlighted.
  const [pinned, setPinned] = useState(null)
  const loadedIds = new Set(papers.map((p) => p.source_id))
  useEffect(() => {
    const handler = async (e) => {
      const sid = e.detail
      if (loadedIds.has(sid)) { setPinned(null); flashEl(document.getElementById(`paper-${sid}`)); return }
      try {
        const res = await fetchPaper(projectId, sid)
        if (res.papers?.length) setPinned(res.papers[0])
      } catch { /* ignore */ }
    }
    window.addEventListener('workbench:reveal-source', handler)
    return () => window.removeEventListener('workbench:reveal-source', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, papers])
  useEffect(() => {
    if (pinned) { const t = setTimeout(() => flashEl(document.getElementById(`paper-${pinned.source_id}`)), 60); return () => clearTimeout(t) }
  }, [pinned])

  const onScroll = (e) => {
    const el = e.currentTarget
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 240 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 pt-4 pb-3 border-b border-slate-100">
        <div className="flex items-center justify-between mb-2.5">
          <h2 className="text-sm font-semibold text-slate-700">Papers</h2>
          <span className="text-xs text-slate-400">{total.toLocaleString()}</span>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); setQ(term.trim()) }} className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search title, DOI, or PMID…"
            className="w-full pl-8 pr-7 py-1.5 text-xs rounded-lg border border-slate-200 bg-slate-50
                       focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white"
          />
          {term && (
            <button
              type="button"
              onClick={() => setTerm('')}
              title="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <X size={13} />
            </button>
          )}
        </form>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-0.5" onScroll={onScroll}>
        {pinned && !loadedIds.has(pinned.source_id) && (
          <div className="mb-1 pb-1 border-b border-dashed border-slate-200">
            <div className="flex items-center justify-between px-2.5 pt-1">
              <span className="text-[10px] uppercase tracking-wider text-blue-500">Cited source</span>
              <button onClick={() => setPinned(null)} className="text-[10px] text-slate-400 hover:text-slate-600">dismiss</button>
            </div>
            <PaperRow p={pinned} onLocate={onLocate} />
          </div>
        )}
        {papers.length === 0 && !pinned ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-4">
            <FileText size={22} className="mb-2 opacity-40" />
            <p className="text-xs">{q ? 'No matching papers.' : 'No papers yet.'}</p>
          </div>
        ) : (
          <>
            {papers.map((p) => <PaperRow key={p.source_id} p={p} onLocate={onLocate} />)}
            {isFetchingNextPage && (
              <div className="flex justify-center py-3 text-slate-400"><Loader2 size={15} className="animate-spin" /></div>
            )}
            {!hasNextPage && papers.length > PAGE && (
              <p className="text-center text-[10px] text-slate-300 py-3">All {total.toLocaleString()} papers loaded</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
