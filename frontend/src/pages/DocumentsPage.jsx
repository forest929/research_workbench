import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDocuments, ingestDocument } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import Badge from '../components/Badge'
import { FileText, Plus, CheckCircle, Clock, Upload } from 'lucide-react'

export default function DocumentsPage() {
  const { id: projectId } = useParams()
  const qc = useQueryClient()
  const [form, setForm] = useState({ source_id: '', content: '', doc_type: 'abstract' })
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const { data: docs = [], isLoading, refetch } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => fetchDocuments(projectId),
    refetchInterval: 10_000,
  })

  const { mutate, isPending } = useMutation({
    mutationFn: () => ingestDocument(projectId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents', projectId] })
      setForm({ source_id: '', content: '', doc_type: 'abstract' })
      setShowForm(false)
      setSuccess('Document ingested — embedding in background.')
      setTimeout(() => setSuccess(''), 4000)
    },
    onError: (e) => setError(e.message),
  })

  function handleSubmit(e) {
    e.preventDefault()
    if (!form.content.trim()) {
      setError('Document content is required.')
      return
    }
    setError('')
    mutate()
  }

  const embedded = docs.filter((d) => d.embedded).length
  const pending = docs.filter((d) => !d.embedded).length

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Documents</h1>
          <p className="text-sm text-slate-500">
            {docs.length} total · {embedded} embedded · {pending} pending
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary text-xs" onClick={() => refetch()}>
            Refresh
          </button>
          <button className="btn-primary text-xs" onClick={() => setShowForm(true)}>
            <Plus size={14} /> Add Document
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {success && (
          <div className="flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
            <CheckCircle size={16} />
            {success}
          </div>
        )}

        {/* Add form */}
        {showForm && (
          <div className="card p-5">
            <h3 className="text-sm font-semibold text-slate-800 mb-4">Add Document</h3>
            <form onSubmit={handleSubmit} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Source ID (DOI / PMID)</label>
                  <input
                    className="input"
                    placeholder="10.1234/example"
                    value={form.source_id}
                    onChange={(e) => setForm((f) => ({ ...f, source_id: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="label">Document Type</label>
                  <select
                    className="input"
                    value={form.doc_type}
                    onChange={(e) => setForm((f) => ({ ...f, doc_type: e.target.value }))}
                  >
                    <option value="abstract">Abstract</option>
                    <option value="fulltext">Full text</option>
                    <option value="trial">Clinical trial</option>
                    <option value="guideline">Guideline</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Content *</label>
                <textarea
                  className="textarea"
                  rows={8}
                  placeholder="Paste abstract or document text here…"
                  value={form.content}
                  onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                />
              </div>
              {error && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}
              <div className="flex gap-2">
                <button type="submit" className="btn-primary" disabled={isPending}>
                  {isPending ? <LoadingSpinner size="sm" /> : <Upload size={14} />}
                  {isPending ? 'Ingesting…' : 'Ingest'}
                </button>
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Document list */}
        {isLoading ? (
          <div className="flex justify-center py-10"><LoadingSpinner label="Loading documents…" /></div>
        ) : docs.length === 0 ? (
          <div className="text-center py-16 text-slate-400">
            <FileText size={40} className="mx-auto mb-3 opacity-40" />
            <p className="font-medium">No documents yet</p>
            <p className="text-sm mt-1">Add source documents to begin analysis</p>
          </div>
        ) : (
          <div className="space-y-2">
            {docs.map((doc) => (
              <div key={doc.id} className="card px-4 py-3 flex items-center gap-4">
                <div className="shrink-0">
                  {doc.embedded ? (
                    <CheckCircle size={18} className="text-emerald-500" />
                  ) : (
                    <Clock size={18} className="text-amber-400 animate-pulse" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-800 truncate">
                      {doc.source_id || doc.id.slice(0, 16)}
                    </span>
                    <Badge color="slate">{doc.doc_type}</Badge>
                    {doc.embedded && (
                      <Badge color="green">{doc.chunk_count} chunks</Badge>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {doc.embedded ? 'Embedded' : 'Embedding in background…'} · {new Date(doc.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
