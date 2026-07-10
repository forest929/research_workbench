import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDocuments, triggerSearch, fetchIngestStatus } from '../api'
import SourceLink from '../components/SourceLink'
import LoadingSpinner from '../components/LoadingSpinner'
import Badge from '../components/Badge'
import {
  Search, Database, CheckCircle, Clock, Zap, AlertCircle,
  BookOpen, Newspaper, ChevronDown, ChevronUp,
} from 'lucide-react'

const SOURCES = [
  { id: 'pubmed', label: 'PubMed', icon: BookOpen, description: 'Biomedical & life sciences abstracts' },
  { id: 'arxiv',  label: 'arXiv',  icon: Newspaper, description: 'Physics, CS, math, biology preprints' },
]

function ProgressRing({ pct, size = 48, stroke = 4 }) {
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ - (pct / 100) * circ
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={stroke} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#2563eb" strokeWidth={stroke}
        strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.5s ease' }} />
    </svg>
  )
}

function LiveLog({ entries }) {
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [entries.length])
  if (!entries.length) return null
  return (
    <div className="bg-slate-900 rounded-xl p-4 font-mono text-xs max-h-40 overflow-y-auto space-y-0.5">
      {entries.map((e, i) => (
        <div key={i} className={e.type === 'error' ? 'text-red-400' : e.type === 'success' ? 'text-emerald-400' : 'text-slate-300'}>
          <span className="text-slate-500 mr-2">{e.time}</span>{e.msg}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}

export default function IngestPage() {
  const { id: projectId } = useParams()
  const qc = useQueryClient()

  const [query, setQuery] = useState('')
  const [sources, setSources] = useState(['pubmed', 'arxiv'])
  const [maxRecords, setMaxRecords] = useState(200)
  const [showDocs, setShowDocs] = useState(false)
  const [log, setLog] = useState([])
  const [polling, setPolling] = useState(false)

  function addLog(msg, type = 'info') {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setLog((l) => [...l, { msg, type, time }])
  }

  // Live ingest status
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['ingest-status', projectId],
    queryFn: () => fetchIngestStatus(projectId),
    refetchInterval: polling ? 2000 : false,
    enabled: true,
  })

  // Watch for completion
  useEffect(() => {
    if (!status) return
    if (status.status === 'done') {
      setPolling(false)
      addLog(`Done — ${status.db_total} documents, ${status.db_embedded} embedded`, 'success')
      qc.invalidateQueries({ queryKey: ['documents', projectId] })
    }
    if (status.status === 'error') {
      setPolling(false)
      addLog(`Error: ${status.error}`, 'error')
    }
  }, [status?.status])

  const { data: docs = [] } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => fetchDocuments(projectId),
    refetchInterval: polling ? 5000 : 30000,
  })

  const { mutate: search, isPending: isStarting } = useMutation({
    mutationFn: () => triggerSearch(projectId, { query, sources, max_records: maxRecords }),
    onSuccess: () => {
      setLog([])
      addLog(`Starting search: "${query}" on ${sources.join(', ')}…`)
      setPolling(true)
    },
    onError: (e) => addLog(`Failed to start: ${e.message}`, 'error'),
  })

  const isRunning = status?.status === 'running' || status?.status === 'embedding' || polling
  const dbTotal   = status?.db_total   ?? docs.length
  const dbEmb     = status?.db_embedded ?? docs.filter((d) => d.embedded).length
  const dbPending = status?.db_pending  ?? docs.filter((d) => !d.embedded).length
  const progress  = dbTotal > 0 ? Math.round((dbEmb / dbTotal) * 100) : 0

  function toggleSource(id) {
    setSources((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-200 bg-white shrink-0">
        <h1 className="text-lg font-semibold text-slate-900">Literature Search</h1>
        <p className="text-sm text-slate-500">
          Search PubMed and arXiv to populate your corpus — the system fetches, chunks, and embeds papers in the background.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-5">

          {/* Search form */}
          <div className="card p-5 space-y-4">
            <div>
              <label className="label">Search query</label>
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  className="input pl-9 text-base"
                  placeholder="e.g. carbapenem resistant bacteria, climate change adaptation…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !isRunning && query.trim() && search()}
                />
              </div>
            </div>

            {/* Sources */}
            <div>
              <label className="label mb-2 block">Sources</label>
              <div className="flex gap-3">
                {SOURCES.map(({ id, label, icon: Icon, description }) => (
                  <button
                    key={id}
                    onClick={() => toggleSource(id)}
                    className={`flex-1 flex items-center gap-3 px-4 py-3 rounded-xl border-2 text-left transition-all
                      ${sources.includes(id)
                        ? 'border-blue-500 bg-blue-50 text-blue-800'
                        : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}
                  >
                    <Icon size={18} className={sources.includes(id) ? 'text-blue-500' : 'text-slate-400'} />
                    <div>
                      <p className="font-semibold text-sm">{label}</p>
                      <p className="text-xs opacity-70">{description}</p>
                    </div>
                    {sources.includes(id) && (
                      <CheckCircle size={14} className="ml-auto text-blue-500 shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Max records */}
            <div>
              <div className="flex justify-between mb-1">
                <label className="label mb-0">Max records</label>
                <span className="text-sm font-medium text-slate-700">{maxRecords}</span>
              </div>
              <input
                type="range" min={50} max={2000} step={50}
                value={maxRecords}
                onChange={(e) => setMaxRecords(Number(e.target.value))}
                className="w-full accent-blue-600"
              />
              <div className="flex justify-between text-xs text-slate-400 mt-0.5">
                <span>50 — quick test</span>
                <span>2000 — full sweep</span>
              </div>
            </div>

            <button
              className="btn-primary w-full justify-center py-2.5"
              onClick={() => search()}
              disabled={isRunning || isStarting || !query.trim() || sources.length === 0}
            >
              {isRunning ? (
                <><LoadingSpinner size="sm" /> Ingesting…</>
              ) : (
                <><Zap size={15} /> Fetch &amp; Embed Papers</>
              )}
            </button>
          </div>

          {/* Live progress */}
          {(isRunning || status?.status === 'done' || status?.status === 'error') && (
            <div className="card p-5 space-y-4">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <ProgressRing pct={progress} />
                  <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-slate-700">
                    {progress}%
                  </span>
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    {isRunning && <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />}
                    {status?.status === 'done' && <CheckCircle size={14} className="text-emerald-500" />}
                    {status?.status === 'error' && <AlertCircle size={14} className="text-red-500" />}
                    <span className="text-sm font-medium text-slate-800 capitalize">
                      {status?.status === 'embedding' ? 'Embedding…' :
                       status?.status === 'done'      ? 'Complete' :
                       status?.status === 'error'     ? 'Failed' :
                       status?.status === 'running'   ? 'Fetching papers…' : 'Idle'}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-center">
                    {[
                      { label: 'Fetched', value: status?.fetched ?? 0 },
                      { label: 'Ingested', value: dbTotal },
                      { label: 'Embedded', value: dbEmb },
                    ].map(({ label, value }) => (
                      <div key={label} className="bg-slate-50 rounded-lg py-2">
                        <p className="text-lg font-bold text-slate-900">{value}</p>
                        <p className="text-xs text-slate-500">{label}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="bg-slate-100 rounded-full h-1.5">
                <div className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }} />
              </div>

              <LiveLog entries={log} />
            </div>
          )}

          {/* Corpus summary */}
          {dbTotal > 0 && (
            <div className="card p-4">
              <button
                className="w-full flex items-center justify-between text-sm font-medium text-slate-700"
                onClick={() => setShowDocs((o) => !o)}
              >
                <div className="flex items-center gap-2">
                  <Database size={15} className="text-slate-400" />
                  Corpus — {dbTotal} documents
                  <Badge color={dbPending > 0 ? 'amber' : 'green'}>
                    {dbPending > 0 ? `${dbPending} pending embed` : 'all embedded'}
                  </Badge>
                </div>
                {showDocs ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              </button>

              {showDocs && (
                <div className="mt-3 border-t border-slate-100 pt-3 space-y-1.5 max-h-80 overflow-y-auto">
                  {docs.map((doc) => (
                    <div key={doc.id} className="flex items-center gap-3 py-1.5">
                      <div className="shrink-0">
                        {doc.embedded
                          ? <CheckCircle size={14} className="text-emerald-500" />
                          : <Clock size={14} className="text-amber-400 animate-pulse" />}
                      </div>
                      <SourceLink id={doc.source_id} short />
                      <Badge color="slate">{doc.doc_type}</Badge>
                      {doc.embedded && (
                        <span className="text-xs text-slate-400 ml-auto">{doc.chunk_count} chunks</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {dbTotal === 0 && !isRunning && (
            <div className="text-center py-10 text-slate-400">
              <Search size={36} className="mx-auto mb-3 opacity-30" />
              <p className="font-medium">No documents yet</p>
              <p className="text-sm mt-1">Enter a search term above to fetch papers from PubMed and arXiv</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
