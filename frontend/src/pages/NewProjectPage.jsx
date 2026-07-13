import { useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { createProject, triggerSearch, ingestFiles, ingestDois } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { ArrowLeft, Search, Upload, Link2, FolderOpen, X, Plus } from 'lucide-react'

const INGEST_MODES = [
  { id: 'search', label: 'Search & retrieve', icon: Search, description: 'Search PubMed (+ Scholar / arXiv) and pull abstracts' },
  { id: 'files', label: 'Upload files', icon: Upload, description: 'CSV, Excel, or PDFs — files or a whole folder' },
  { id: 'dois', label: 'DOI list', icon: Link2, description: 'Paste DOIs to resolve and import' },
]

const SEARCH_SOURCES = [
  { id: 'pubmed', label: 'PubMed', hint: 'clinical / biomedical' },
  { id: 'scholar', label: 'Google Scholar' },
  { id: 'arxiv', label: 'arXiv', hint: 'preprints' },
]

export default function NewProjectPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const folderRef = useRef(null)

  const [form, setForm] = useState({ name: '', description: '', scope_statement: '' })
  const [ingestMode, setIngestMode] = useState('search')
  const [maxRecords, setMaxRecords] = useState(30)
  const [searchQuery, setSearchQuery] = useState('')
  const [sources, setSources] = useState(['pubmed'])
  const [files, setFiles] = useState([])
  const [doiText, setDoiText] = useState('')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  const parsedDois = doiText.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean)
  const toggleSource = (id) =>
    setSources((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim() || !form.scope_statement.trim()) {
      setError('Add a project name and a research question.'); return
    }
    if (ingestMode === 'search') {
      if (!(searchQuery.trim() || form.scope_statement.trim())) { setError('Enter search terms.'); return }
      if (sources.length === 0) { setError('Pick at least one source.'); return }
    }
    if (ingestMode === 'files' && files.length === 0) { setError('Add one or more files or a folder.'); return }
    if (ingestMode === 'dois' && parsedDois.length === 0) { setError('Paste at least one DOI.'); return }
    setError('')
    setCreating(true)
    try {
      const project = await createProject(form)
      qc.invalidateQueries({ queryKey: ['projects'] })
      if (ingestMode === 'search') {
        await triggerSearch(project.id, { query: searchQuery.trim() || form.scope_statement.trim(), sources, max_records: maxRecords })
      } else if (ingestMode === 'files') {
        await ingestFiles(project.id, files)
      } else if (ingestMode === 'dois') {
        await ingestDois(project.id, parsedDois)
      }
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setError(err.message || 'Could not create the project.')
      setCreating(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-8 py-10">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 mb-6">
          <ArrowLeft size={15} /> Projects
        </Link>

        <div className="border-b border-slate-200 pb-5 mb-7">
          <h1 className="font-display text-3xl text-slate-900 leading-none">New review</h1>
          <p className="text-sm text-slate-500 mt-2">
            Name your review, state the question, and choose where the papers come from. Analysis is a separate step you run next.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-7">
          {/* Basics */}
          <div className="space-y-4">
            <div>
              <label className="label">Project name</label>
              <input
                className="input"
                placeholder="e.g. PARP inhibitors in ovarian cancer"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="label">Research question</label>
              <p className="text-xs text-slate-400 mb-1.5">
                What you're reviewing. Used as the search query when the search box is blank, and to seed the disease filter.
              </p>
              <textarea
                className="textarea"
                rows={3}
                placeholder="e.g. Evidence for olaparib and niraparib in ovarian cancer maintenance — efficacy on progression-free survival and the role of BRCA / HRD status."
                value={form.scope_statement}
                onChange={(e) => setForm((f) => ({ ...f, scope_statement: e.target.value }))}
              />
            </div>
          </div>

          {/* Source */}
          <div>
            <p className="section-title mb-3">Where the papers come from</p>
            <div className="grid grid-cols-3 gap-2.5">
              {INGEST_MODES.map(({ id, label, icon: Icon, description }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setIngestMode(id)}
                  className={`flex flex-col gap-1.5 px-3.5 py-3 rounded-xl border text-left transition-all
                    ${ingestMode === id ? 'border-blue-500 bg-blue-50/60 ring-1 ring-blue-200' : 'border-slate-200 bg-white hover:border-slate-300'}`}
                >
                  <Icon size={16} className={ingestMode === id ? 'text-blue-600' : 'text-slate-400'} />
                  <span className={`text-sm font-medium ${ingestMode === id ? 'text-blue-900' : 'text-slate-700'}`}>{label}</span>
                  <span className="text-[11px] text-slate-500 leading-tight">{description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Search mode */}
          {ingestMode === 'search' && (
            <div className="space-y-4 rounded-xl border border-slate-200 p-4">
              <div>
                <label className="label">Search terms</label>
                <input
                  className="input"
                  placeholder="e.g. olaparib ovarian cancer maintenance progression-free survival"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <p className="text-xs text-slate-400 mt-1">Leave blank to search with your research question.</p>
              </div>
              <div>
                <label className="label">Sources</label>
                <div className="flex flex-wrap gap-2">
                  {SEARCH_SOURCES.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => toggleSource(s.id)}
                      className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                        sources.includes(s.id) ? 'border-blue-500 bg-blue-100 text-blue-800 font-medium' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'
                      }`}
                    >
                      {s.label}{s.hint && <span className="ml-1 text-[10px] opacity-70">· {s.hint}</span>}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-400 mt-1.5">PubMed is recommended for clinical/biomedical reviews — reliable peer-reviewed abstracts.</p>
              </div>
              <div>
                <div className="flex justify-between mb-1">
                  <label className="label mb-0">How many papers</label>
                  <span className="text-sm font-medium text-slate-600">{maxRecords}</span>
                </div>
                <input type="range" min={20} max={200} step={10} value={maxRecords}
                  onChange={(e) => setMaxRecords(Number(e.target.value))} className="w-full accent-blue-600" />
                <div className="flex justify-between text-[11px] text-slate-400 mt-0.5"><span>20 · focused &amp; fast</span><span>200 · broad</span></div>
                <p className="text-[11px] text-slate-400 mt-1">Fewer, most-relevant papers build faster. Retrieved by relevance, shown newest first.</p>
              </div>
            </div>
          )}

          {/* Files mode */}
          {ingestMode === 'files' && (
            <div className="rounded-xl border border-slate-200 p-4">
              <div className="flex items-center justify-between mb-1.5">
                <label className="label mb-0">Files or folder</label>
                <button type="button" onClick={() => folderRef.current?.click()} className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800">
                  <FolderOpen size={13} /> Select a folder
                </button>
              </div>
              <div
                className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors
                  ${files.length ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 hover:border-blue-300 hover:bg-blue-50/30'}`}
                onClick={() => fileRef.current?.click()}
              >
                {files.length ? (
                  <div className="text-emerald-700">
                    <div className="flex items-center justify-center gap-2">
                      <Upload size={16} />
                      <span className="text-sm font-medium">{files.length} file{files.length === 1 ? '' : 's'} selected</span>
                      <button type="button" className="ml-1 text-slate-400 hover:text-red-500" onClick={(e) => { e.stopPropagation(); setFiles([]) }}><X size={14} /></button>
                    </div>
                    <p className="text-[11px] text-emerald-600/80 mt-1 truncate">{files.slice(0, 4).map((f) => f.name).join(', ')}{files.length > 4 ? '…' : ''}</p>
                  </div>
                ) : (
                  <>
                    <Upload size={20} className="mx-auto mb-1.5 text-slate-400" />
                    <p className="text-sm text-slate-500">Choose CSV, Excel, or PDF files</p>
                    <p className="text-xs text-slate-400 mt-0.5">PDFs import by extracted text · select many at once</p>
                  </>
                )}
              </div>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.pdf" multiple className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []))} />
              <input ref={folderRef} type="file" webkitdirectory="" directory="" multiple className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []).filter((f) => /\.(csv|xlsx?|pdf)$/i.test(f.name)))} />
              <p className="text-xs text-slate-400 mt-1.5">CSV/Excel need a <span className="font-medium">title</span> or <span className="font-medium">abstract</span> column (optional: authors, journal, year, doi, url).</p>
            </div>
          )}

          {/* DOI mode */}
          {ingestMode === 'dois' && (
            <div className="rounded-xl border border-slate-200 p-4 space-y-2">
              <label className="label">DOIs</label>
              <textarea className="textarea font-mono text-xs" rows={5}
                placeholder={'One per line, e.g.\n10.1056/NEJMoa1810858\n10.1016/S0140-6736(21)00306-8'}
                value={doiText} onChange={(e) => setDoiText(e.target.value)} />
              <p className="text-xs text-slate-400">
                {parsedDois.length} DOI{parsedDois.length === 1 ? '' : 's'} detected · resolved via PubMed, then Crossref. Unresolvable ones are skipped (you'll see which).
              </p>
            </div>
          )}

          {error && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>}

          <div className="flex items-center gap-2 pt-1 border-t border-slate-100">
            <button type="submit" disabled={creating}
              className="mt-4 inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-60 transition-colors">
              {creating ? <LoadingSpinner size="sm" /> : <Plus size={16} />}
              {creating ? 'Creating…' : 'Create review'}
            </button>
            <Link to="/" className="mt-4 px-4 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors">Cancel</Link>
          </div>
        </form>
      </div>
    </div>
  )
}
