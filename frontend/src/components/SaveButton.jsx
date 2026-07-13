import { useParams } from 'react-router-dom'
import { Bookmark, BookmarkCheck } from 'lucide-react'
import useReadingList from '../hooks/useReadingList'

/**
 * Bookmark toggle for a single publication. Self-contained: reads the active
 * project from the route and drives the reading-list hook, so callers only pass
 * the source metadata. Renders as an icon button (compact) or an icon+label
 * chip (`showLabel`).
 */
export default function SaveButton({ source_id, doi = null, title = null, added_from = 'conversation', showLabel = false }) {
  const { id: projectId } = useParams()
  const { isSaved, toggle } = useReadingList(projectId)

  if (!source_id) return null
  const saved = isSaved(source_id)
  const Icon = saved ? BookmarkCheck : Bookmark

  // When labelled, render as a clear bordered chip so "save to reading list" is
  // obvious; the icon-only variant stays compact.
  const base = 'inline-flex items-center gap-1 font-medium transition-colors'
  const labelled = showLabel
    ? `text-xs rounded-md px-2 py-1 border ${saved
        ? 'text-blue-700 bg-blue-50 border-blue-200 hover:bg-blue-100'
        : 'text-blue-600 bg-white border-blue-300 hover:bg-blue-50'}`
    : `text-[10px] rounded px-1.5 py-0.5 ${saved
        ? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
        : 'text-slate-400 hover:text-blue-600 hover:bg-blue-50'}`

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        toggle({ source_id, doi, title, added_from })
      }}
      title={saved ? 'Remove from reading list' : 'Save to reading list'}
      aria-pressed={saved}
      className={`${base} ${labelled}`}
    >
      <Icon size={showLabel ? 13 : 12} />
      {showLabel && (saved ? 'Saved' : 'Save')}
    </button>
  )
}
