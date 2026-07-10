import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchProjects, createProject, triggerSearch, api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import Badge from '../components/Badge'
import { Plus, ArrowRight, Beaker, Search, Upload, X } from 'lucide-react'

const STATE_BADGE = {
  awaiting_review: 'amber',
  complete: 'green',
  running: 'blue',
  analyzing: 'blue',
  death_spiral: 'red',
  onboarding: 'slate',
  ingesting: 'purple',
}

// Two ingest modes on project creation
const INGEST_MODES = [
  { id: 'search', label: 'Auto-search the web', icon: Search, description: 'System searches Google Scholar + arXiv using your scope as the query' },
  { id: 'upload', label: 'Upload my own dataset', icon: Upload, description: 'CSV, Excel, or Google Sheets — bring your own list of papers' },
]

export default function ProjectsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef(null)

  const [form, setForm] = useState({ name: '', description: '', scope_statement: '' })
  const [showForm, setShowForm] = useState(false)
  const [ingestMode, setIngestMode] = useState('search')
  const [maxRecords, setMaxRecords] = useState(200)
  const [file, setFile] = useState(null)
  const [sheetsUrl, setSheetsUrl] = useState('')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim() || !form.scope_statement.trim()) {
      setError('Project name and scope statement are required.')
      return
    }
    if (ingestMode === 'upload' && !file && !sheetsUrl.trim()) {
      setError('Please choose a file or paste a Google Sheets URL.')
      return
    }
    setError('')
    setCreating(true)

    try {
      // 1. Create the project
      const project = await createProject(form)
      qc.invalidateQueries({ queryKey: ['projects'] })

      if (ingestMode === 'search') {
        // 2a. Fire-and-forget background search using scope statement as query
        await triggerSearch(project.id, {
          query: form.scope_statement,
          sources: ['scholar', 'arxiv'],
          max_records: maxRecords,
        })
        navigate(`/projects/${project.id}/documents`)
      } else {
        // 2b. Upload file if provided
        if (file) {
          const fd = new FormData()
          fd.append('file', file)
          await fetch(`/api/projects/${project.id}/upload`, { method: 'POST', body: fd })
        }
        // Google Sheets URL — parse sheet ID and trigger import
        if (sheetsUrl.trim()) {
          const match = sheetsUrl.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
          if (match) {
            await api.post(`/projects/${project.id}/import-sheets`, { spreadsheet_id: match[1] })
          }
        }
        navigate(`/projects/${project.id}/documents`)
      }
    } catch (err) {
      setError(err.message || 'Failed to create project')
      setCreating(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-10">
        {/* Hero */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-100 mb-4">
            <Beaker size={28} className="text-blue-600" />
          </div>
          <h1 className="text-3xl font-bold text-slate-900 mb-2">AI Portfolio Architect</h1>
          <p className="text-slate-500 max-w-lg mx-auto">
            Transform research into verified inclusion/exclusion criteria with an LLM-as-Judge evaluation layer.
          </p>
        </div>

        {/* Existing projects */}
        {isLoading ? (
          <div className="flex justify-center py-8"><LoadingSpinner label="Loading projects…" /></div>
        ) : projects.length > 0 ? (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
              Your Projects
            </h2>
            <div className="space-y-2">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => navigate(`/projects/${p.id}`)}
                  className="w-full card px-5 py-4 flex items-center gap-4 hover:border-blue-200 hover:shadow-md transition-all text-left group"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-semibold text-slate-900 group-hover:text-blue-700 truncate">
                        {p.name}
                      </span>
                      <Badge color={STATE_BADGE[p.state] || 'slate'}>
                        {p.state?.replace(/_/g, ' ')}
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-400 truncate">
                      {p.iteration_count} iteration{p.iteration_count !== 1 ? 's' : ''} ·{' '}
                      {p.id.slice(0, 8)}
                    </p>
                  </div>
                  <ArrowRight size={16} className="text-slate-300 group-hover:text-blue-500 shrink-0 transition-colors" />
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* Create new project */}
        {!showForm ? (
          <button
            onClick={() => setShowForm(true)}
            className="w-full card px-5 py-4 border-dashed border-2 border-slate-200 hover:border-blue-300
                       hover:bg-blue-50/50 transition-all flex items-center justify-center gap-2
                       text-slate-500 hover:text-blue-600 font-medium"
          >
            <Plus size={16} />
            New Project
          </button>
        ) : (
          <div className="card p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-slate-900">Create New Project</h2>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-slate-600">
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Basic fields */}
              <div>
                <label className="label">Project Name *</label>
                <input
                  className="input"
                  placeholder="e.g., CRE Treatment Evidence 2025"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>

              <div>
                <label className="label">Description</label>
                <textarea
                  className="textarea"
                  rows={2}
                  placeholder="Optional brief description"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>

              <div>
                <label className="label">Scope Statement *</label>
                <p className="text-xs text-slate-400 mb-1.5">
                  Describe what's in/out of scope. Also used as the initial search query.
                </p>
                <textarea
                  className="textarea"
                  rows={5}
                  placeholder={
                    'e.g. carbapenem-resistant Klebsiella pneumoniae treatment evidence\n\n' +
                    'Include:\n• Clinical trials and systematic reviews 2019–2025\n• Drugs: ceftazidime-avibactam, meropenem-vaborbactam\n\n' +
                    'Exclude:\n• Non-clinical in vitro only studies\n• Non-Enterobacterales organisms'
                  }
                  value={form.scope_statement}
                  onChange={(e) => setForm((f) => ({ ...f, scope_statement: e.target.value }))}
                />
              </div>

              {/* Ingest mode */}
              <div>
                <label className="label mb-2 block">Document source</label>
                <div className="grid grid-cols-2 gap-3">
                  {INGEST_MODES.map(({ id, label, icon: Icon, description }) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setIngestMode(id)}
                      className={`flex flex-col items-start gap-1.5 px-4 py-3 rounded-xl border-2 text-left transition-all
                        ${ingestMode === id
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-slate-200 bg-white hover:border-slate-300'}`}
                    >
                      <div className="flex items-center gap-2">
                        <Icon size={16} className={ingestMode === id ? 'text-blue-500' : 'text-slate-400'} />
                        <span className={`text-sm font-semibold ${ingestMode === id ? 'text-blue-800' : 'text-slate-700'}`}>
                          {label}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 leading-tight">{description}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Auto-search options */}
              {ingestMode === 'search' && (
                <div className="bg-blue-50 rounded-xl p-4">
                  <div className="flex justify-between mb-1">
                    <label className="label mb-0 text-blue-800">Max records to fetch</label>
                    <span className="text-sm font-semibold text-blue-700">{maxRecords}</span>
                  </div>
                  <input
                    type="range" min={50} max={1000} step={50}
                    value={maxRecords}
                    onChange={(e) => setMaxRecords(Number(e.target.value))}
                    className="w-full accent-blue-600"
                  />
                  <div className="flex justify-between text-xs text-blue-400 mt-0.5">
                    <span>50 — quick</span><span>1000 — thorough</span>
                  </div>
                  <p className="text-xs text-blue-600 mt-2">
                    Fetches from Google Scholar + arXiv using your scope statement as the query.
                    Runs in the background — you can navigate to the project while it completes.
                  </p>
                </div>
              )}

              {/* Upload options */}
              {ingestMode === 'upload' && (
                <div className="space-y-3">
                  <div>
                    <label className="label">Upload file (CSV or Excel)</label>
                    <div
                      className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors
                        ${file ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 hover:border-blue-300 hover:bg-blue-50/30'}`}
                      onClick={() => fileRef.current?.click()}
                    >
                      {file ? (
                        <div className="flex items-center justify-center gap-2 text-emerald-700">
                          <Upload size={16} />
                          <span className="text-sm font-medium">{file.name}</span>
                          <button
                            type="button"
                            className="ml-2 text-slate-400 hover:text-red-500"
                            onClick={(e) => { e.stopPropagation(); setFile(null) }}
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <>
                          <Upload size={20} className="mx-auto mb-1.5 text-slate-400" />
                          <p className="text-sm text-slate-500">Click to upload CSV or Excel file</p>
                          <p className="text-xs text-slate-400 mt-0.5">Expects columns: title, abstract, authors, year, doi</p>
                        </>
                      )}
                    </div>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".csv,.xlsx,.xls"
                      className="hidden"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                    />
                  </div>

                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <div className="flex-1 h-px bg-slate-200" />
                    <span>or</span>
                    <div className="flex-1 h-px bg-slate-200" />
                  </div>

                  <div>
                    <label className="label">Google Sheets URL</label>
                    <input
                      className="input text-sm"
                      placeholder="https://docs.google.com/spreadsheets/d/…"
                      value={sheetsUrl}
                      onChange={(e) => setSheetsUrl(e.target.value)}
                    />
                    <p className="text-xs text-slate-400 mt-1">
                      Sheet must be publicly readable or shared with the service account.
                    </p>
                  </div>
                </div>
              )}

              {error && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button type="submit" className="btn-primary" disabled={creating}>
                  {creating ? <LoadingSpinner size="sm" /> : <Plus size={14} />}
                  {creating
                    ? ingestMode === 'search' ? 'Creating & starting search…' : 'Creating…'
                    : 'Create Project'}
                </button>
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}
