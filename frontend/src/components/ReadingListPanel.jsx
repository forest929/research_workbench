import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BookMarked, Trash2, FlaskConical, Loader2 } from 'lucide-react'
import useReadingList from '../hooks/useReadingList'
import { spinoffFromReadingList } from '../api'
import SourceLink from './SourceLink'
import AddSourceBar from './AddSourceBar'
import { flashEl } from './PapersPanel'

/** Right column: the saved reading list. Add by DOI, and spin the selection off
 *  into a new review for the next round of research. */
export default function ReadingListPanel({ projectId, onLocate }) {
  const { items, remove } = useReadingList(projectId)
  const navigate = useNavigate()
  const qc = useQueryClient()

  // Reveal a cited paper in the reading list (from a citation click), if saved.
  useEffect(() => {
    const handler = (e) => flashEl(document.getElementById(`reading-${e.detail}`))
    window.addEventListener('workbench:reveal-source', handler)
    return () => window.removeEventListener('workbench:reveal-source', handler)
  }, [])

  const spinoff = useMutation({
    mutationFn: (name) => spinoffFromReadingList(projectId, name),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${res.id}`)
    },
  })
  const startSpinoff = () => {
    if (!items.length) return
    const name = window.prompt(`Start a new review from these ${items.length} papers. Name it:`, '')
    if (name !== null) spinoff.mutate(name.trim())
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 pt-4 pb-3 border-b border-slate-100">
        <div className="flex items-center justify-between mb-2.5">
          <h2 className="text-sm font-semibold text-slate-700">Reading list</h2>
          <span className="text-xs text-slate-400">{items.length}</span>
        </div>
        <AddSourceBar projectId={projectId} onLocate={onLocate} />
        {items.length > 0 && (
          <button
            onClick={startSpinoff}
            disabled={spinoff.isPending}
            title="Create a new review seeded with just these papers"
            className="mt-2 w-full inline-flex items-center justify-center gap-1.5 py-2 rounded-lg border border-blue-300
                       text-blue-600 bg-white text-xs font-medium hover:bg-blue-50 disabled:opacity-60 transition-colors"
          >
            {spinoff.isPending
              ? <><Loader2 size={13} className="animate-spin" /> Creating…</>
              : <><FlaskConical size={13} /> New review from these {items.length}</>}
          </button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-0.5">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-4">
            <BookMarked size={22} className="mb-2 opacity-40" />
            <p className="text-xs">Save papers here as you review. Add one by DOI above, then spin your selection into a new review.</p>
          </div>
        ) : items.map((it) => (
          <div key={it.source_id} id={`reading-${it.source_id}`} className="rounded-lg px-2.5 py-2 hover:bg-slate-50 group scroll-mt-2 transition-shadow duration-300">
            <div className="flex items-start justify-between gap-1.5">
              <div className="min-w-0">
                {(it.journal || it.year) && (
                  <p className="text-[10px] text-slate-400 italic line-clamp-1">
                    {[it.journal, it.year].filter(Boolean).join(' · ')}
                  </p>
                )}
                <p className="text-[13px] font-medium leading-snug text-slate-800 line-clamp-2">
                  {it.title || it.source_id}
                </p>
              </div>
              <button
                onClick={() => remove.mutate(it.source_id)}
                title="Remove"
                className="shrink-0 p-1 rounded text-slate-300 hover:text-red-600 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Trash2 size={13} />
              </button>
            </div>
            {it.authors && <p className="mt-0.5 text-[11px] text-slate-500 line-clamp-1">{it.authors}</p>}
            <div className="mt-1 flex items-center gap-x-2 gap-y-0.5 flex-wrap">
              <SourceLink id={it.source_id} />
              {it.doi && <SourceLink id={it.doi} />}
            </div>
            {it.note && <p className="mt-1 text-[11px] text-slate-500 italic line-clamp-2">{it.note}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}
