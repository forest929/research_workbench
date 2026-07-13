import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { BookMarked, Trash2, Calendar, Pencil, Plus, Check, X } from 'lucide-react'
import useReadingList from '../hooks/useReadingList'
import AddSourceBar from '../components/AddSourceBar'
import SourceLink from '../components/SourceLink'
import LoadingSpinner from '../components/LoadingSpinner'

const FROM_LABEL = {
  doi: 'Added by DOI',
  conversation: 'Saved from conversation',
  cluster: 'Saved from cluster',
  filter: 'Saved from drug/disease filter',
  paper_list: 'Saved from paper list',
}

function formatDate(v) {
  if (!v) return null
  // stored as "YYYY-MM-DD HH:MM:SS" (UTC) by SQLite datetime('now')
  const d = new Date(String(v).replace(' ', 'T') + 'Z')
  return isNaN(d) ? null : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Inline note editor for one saved publication. Reads collapsed; click to edit,
 *  Save upserts the note (added_from omitted → provenance preserved). */
function NoteEditor({ item, onSave, saving }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.note || '')

  if (!editing) {
    return item.note ? (
      <button
        onClick={() => { setDraft(item.note); setEditing(true) }}
        className="mt-1.5 group flex items-start gap-1.5 text-left"
        title="Edit note"
      >
        <span className="text-xs text-slate-500 italic">{item.note}</span>
        <Pencil size={11} className="mt-0.5 shrink-0 text-slate-300 group-hover:text-blue-500" />
      </button>
    ) : (
      <button
        onClick={() => { setDraft(''); setEditing(true) }}
        className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-blue-600"
      >
        <Plus size={11} /> Add note
      </button>
    )
  }

  const commit = () => {
    onSave(draft.trim())        // "" clears the note; provenance is preserved
    setEditing(false)
  }

  return (
    <div className="mt-1.5 flex items-start gap-1.5">
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit()
          if (e.key === 'Escape') setEditing(false)
        }}
        rows={2}
        placeholder="Why this paper matters…"
        className="flex-1 text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 resize-y
                   focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
      <div className="flex flex-col gap-1">
        <button onClick={commit} disabled={saving} title="Save (⌘/Ctrl+Enter)"
          className="p-1 rounded text-emerald-600 hover:bg-emerald-50 disabled:opacity-50">
          <Check size={14} />
        </button>
        <button onClick={() => setEditing(false)} title="Cancel (Esc)"
          className="p-1 rounded text-slate-400 hover:bg-slate-100">
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

export default function ReadingListPage() {
  const { id: projectId } = useParams()
  const { items, isLoading, remove, save } = useReadingList(projectId)

  return (
    <div className="h-full flex flex-col bg-slate-50">
      {/* Header */}
      <div className="px-6 pt-5 pb-4 border-b border-slate-200 bg-white">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <BookMarked size={17} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-800 leading-none">Reading list</h1>
            <p className="text-xs text-slate-400 mt-1">
              {items.length} curated publication{items.length === 1 ? '' : 's'} for this project
            </p>
          </div>
        </div>

        {/* Add by DOI — also lands here automatically once resolved */}
        <div className="mt-4">
          <AddSourceBar projectId={projectId} onLocate={() => {}} />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-6 border border-dashed border-slate-200 rounded-xl bg-white">
            <BookMarked size={30} className="mb-3 opacity-40" />
            <p className="text-sm font-medium text-slate-500">No saved publications yet</p>
            <p className="text-xs mt-1 max-w-sm">
              Bookmark sources with the <span className="font-medium">Save</span> button while reviewing
              clusters and conversations, or add one by DOI above.
            </p>
          </div>
        ) : (
          <ul className="max-w-3xl mx-auto space-y-2">
            {items.map((it) => (
              <li key={it.source_id} className="card px-4 py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {it.title ? (
                    <p className="text-sm font-medium text-slate-800 leading-snug">{it.title}</p>
                  ) : (
                    <p className="text-sm font-medium text-slate-500 font-mono">{it.source_id}</p>
                  )}
                  {it.authors && (
                    <p className="mt-0.5 text-xs text-slate-500 leading-snug">{it.authors}</p>
                  )}
                  {(it.journal || it.year) && (
                    <p className="mt-0.5 text-[11px] text-slate-400 italic">
                      {[it.journal, it.year].filter(Boolean).join(' · ')}
                    </p>
                  )}
                  <div className="mt-1.5 flex items-center gap-x-2.5 gap-y-1 flex-wrap">
                    <SourceLink id={it.source_id} />
                    {it.doi && <SourceLink id={it.doi} />}
                    <span className="text-[10px] uppercase tracking-wide text-slate-400">
                      {FROM_LABEL[it.added_from] || it.added_from}
                    </span>
                    {formatDate(it.created_at) && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
                        <Calendar size={10} /> {formatDate(it.created_at)}
                      </span>
                    )}
                  </div>
                  <NoteEditor
                    item={it}
                    saving={save.isPending}
                    onSave={(note) => save.mutate({ source_id: it.source_id, note })}
                  />
                </div>
                <button
                  onClick={() => remove.mutate(it.source_id)}
                  disabled={remove.isPending}
                  title="Remove from reading list"
                  className="shrink-0 p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
