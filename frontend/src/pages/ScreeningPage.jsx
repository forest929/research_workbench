import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchScreeningQueue, fetchScreeningStats, fetchPreferences,
  llmPredict, recordDecision,
} from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import ConfidenceBar from '../components/ConfidenceBar'
import Badge from '../components/Badge'
import {
  CheckCircle, XCircle, RotateCcw, ChevronDown, ChevronRight,
  Brain, Users, Lightbulb, BarChart2, BookOpen, Sparkles,
  Download, FileSpreadsheet, Sheet,
} from 'lucide-react'
import SourceLink from '../components/SourceLink'
import { exportCsvUrl, exportExcelUrl, exportGoogleSheets } from '../api'

const REASON_CODES = [
  'REVIEW_ARTICLE', 'SIMULATION_ONLY', 'GREENHOUSE_ONLY',
  'WRONG_POPULATION', 'WRONG_INTERVENTION', 'WRONG_OUTCOME',
  'PROTOCOL_PAPER', 'DUPLICATE', 'LANGUAGE', 'DATE', 'NO_ABSTRACT', 'OTHER',
]
const REASON_LABELS = {
  REVIEW_ARTICLE: 'Review article',
  SIMULATION_ONLY: 'Simulation only',
  GREENHOUSE_ONLY: 'Greenhouse-only experiment',
  WRONG_POPULATION: 'Wrong population',
  WRONG_INTERVENTION: 'Wrong intervention',
  WRONG_OUTCOME: 'Wrong outcome',
  PROTOCOL_PAPER: 'Protocol / registration paper',
  DUPLICATE: 'Duplicate record',
  LANGUAGE: 'Non-English',
  DATE: 'Outside date range',
  NO_ABSTRACT: 'No abstract',
  OTHER: 'Other',
}

function parseDoc(raw = '') {
  const KNOWN = new Set(['Title', 'Authors', 'Journal', 'Year', 'DOI', 'Abstract', 'PMID', 'Source', 'Type', 'Language', 'Keywords'])
  const fields = {}
  let currentKey = null
  for (const line of raw.split('\n')) {
    if (line.includes(': ')) {
      const idx = line.indexOf(': ')
      const k = line.slice(0, idx).trim()
      const v = line.slice(idx + 2).trim()
      if (KNOWN.has(k) || !currentKey) {
        currentKey = k
        fields[k] = v
        continue
      }
    }
    if (currentKey && line.trim()) {
      fields[currentKey] = (fields[currentKey] || '') + ' ' + line.trim()
    }
  }
  return fields
}

// ── Queue item ────────────────────────────────────────────────────────────────
function QueueItem({ doc, isActive, onClick }) {
  const parsed = parseDoc(doc.content)
  const title = parsed.Title || doc.source_id || doc.id.slice(0, 12)
  const alLabel = doc.al_label
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-3 border-b border-slate-100 transition-colors
        ${isActive ? 'bg-blue-50 border-l-2 border-l-blue-500' : 'hover:bg-slate-50'}`}
    >
      <div className="flex items-start gap-2">
        {alLabel === 'include' && <CheckCircle size={13} className="text-emerald-400 mt-0.5 shrink-0" />}
        {alLabel === 'exclude' && <XCircle size={13} className="text-red-400 mt-0.5 shrink-0" />}
        {!alLabel && <div className="w-3 h-3 rounded-full border border-slate-200 mt-0.5 shrink-0" />}
        <p className="text-xs font-medium text-slate-700 leading-snug line-clamp-2">{title}</p>
      </div>
      {doc.al_confidence > 0 && (
        <div className="flex items-center gap-1 mt-1 ml-5">
          <div className="flex-1 bg-slate-100 rounded-full h-0.5">
            <div
              className={`h-0.5 rounded-full ${alLabel === 'include' ? 'bg-emerald-400' : 'bg-red-400'}`}
              style={{ width: `${Math.round(doc.al_confidence * 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-slate-400">{Math.round(doc.al_confidence * 100)}%</span>
        </div>
      )}
    </button>
  )
}

// ── Similar example ───────────────────────────────────────────────────────────
function SimilarExample({ ex }) {
  const [open, setOpen] = useState(false)
  const isInclude = ex.human_label === 'include'
  const reason = ex.human_reason || REASON_LABELS[ex.reason_code] || ''
  return (
    <div className="border border-slate-100 rounded-lg overflow-hidden">
      <button
        className="w-full text-left px-3 py-2 flex items-center gap-2 bg-slate-50 hover:bg-slate-100 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        {isInclude ? (
          <CheckCircle size={12} className="text-emerald-500 shrink-0" />
        ) : (
          <XCircle size={12} className="text-red-500 shrink-0" />
        )}
        <span className={`text-xs font-medium ${isInclude ? 'text-emerald-700' : 'text-red-700'}`}>
          {ex.human_label?.toUpperCase()}
        </span>
        <span className="flex-1 min-w-0 truncate"><SourceLink id={ex.source_id} short /></span>
        <span className="text-[10px] text-slate-400 shrink-0">sim {(ex.similarity || 0).toFixed(2)}</span>
        {open ? <ChevronDown size={10} className="text-slate-300" /> : <ChevronRight size={10} className="text-slate-300" />}
      </button>
      {open && (
        <div className="px-3 py-2 bg-white">
          {reason && <p className="text-xs text-slate-500 mb-1">Reason: {reason}</p>}
          {ex.preview && <p className="text-[11px] text-slate-400 leading-relaxed">{ex.preview.slice(0, 200)}</p>}
        </div>
      )}
    </div>
  )
}

// ── Stats panel ───────────────────────────────────────────────────────────────
function StatsView({ projectId }) {
  const { data: stats } = useQuery({
    queryKey: ['screening-stats', projectId],
    queryFn: () => fetchScreeningStats(projectId),
    refetchInterval: 15_000,
  })
  const { data: prefs } = useQuery({
    queryKey: ['screening-prefs', projectId],
    queryFn: () => fetchPreferences(projectId),
  })

  if (!stats) return <div className="flex justify-center py-8"><LoadingSpinner /></div>

  const agreement = stats.agreement_rate
  return (
    <div className="space-y-5 p-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Total docs', value: stats.total_documents },
          { label: 'Pending', value: stats.pending_documents },
          { label: 'Validated', value: stats.total_decisions },
          { label: 'Agreement', value: agreement != null ? `${(agreement * 100).toFixed(0)}%` : 'N/A' },
        ].map(({ label, value }) => (
          <div key={label} className="card px-4 py-3 text-center">
            <p className="text-2xl font-bold text-slate-900">{value ?? '—'}</p>
            <p className="text-xs text-slate-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {stats.by_direction?.length > 0 && (
        <div>
          <p className="section-title mb-2">Disagreements by direction</p>
          <div className="space-y-1">
            {stats.by_direction.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                <span>{r.llm_label === 'include' ? '✅' : '❌'} LLM → {r.human_label === 'include' ? '✅' : '❌'} Human</span>
                <span className="ml-auto font-medium">{r.cnt}×</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {prefs?.guidance_text && (
        <div>
          <p className="section-title mb-2 flex items-center gap-1.5">
            <Lightbulb size={12} /> Learned preferences
          </p>
          <div className="bg-purple-50 border border-purple-200 rounded-lg px-3 py-2">
            <p className="text-xs text-purple-700 leading-relaxed">{prefs.guidance_text}</p>
          </div>
          <p className="text-[10px] text-slate-400 mt-1">Auto-injected into all future screening prompts</p>
        </div>
      )}

      {prefs?.preferences?.length > 0 && (
        <div>
          <p className="section-title mb-2">Detected patterns</p>
          <div className="space-y-1">
            {prefs.preferences.map((p, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                <span>{p.label === 'include' ? '✅' : '❌'}</span>
                <span>{REASON_LABELS[p.reason_code] || p.reason_code}</span>
                <Badge color="slate">{p.count}×</Badge>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function ScreeningPage() {
  const { id: projectId } = useParams()
  const qc = useQueryClient()

  const [activeDocIdx, setActiveDocIdx] = useState(0)
  const [predictions, setPredictions] = useState({}) // docId → prediction
  const [reasonCode, setReasonCode] = useState('(none)')
  const [humanReason, setHumanReason] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [showAnnotation, setShowAnnotation] = useState(false)
  const [activeTab, setActiveTab] = useState('queue') // 'queue' | 'stats'
  const [toast, setToast] = useState(null)
  const [sessionDecisions, setSessionDecisions] = useState(0)
  const [lastLearnedAt, setLastLearnedAt] = useState(null)
  const [showExport, setShowExport] = useState(false)
  const [sheetsId, setSheetsId] = useState('')
  const [sheetsResult, setSheetsResult] = useState(null)
  const [sheetsExporting, setSheetsExporting] = useState(false)

  const { data: queueData, refetch: refetchQueue, isLoading: queueLoading } = useQuery({
    queryKey: ['screening-queue', projectId],
    queryFn: () => fetchScreeningQueue(projectId, 30),
    refetchInterval: 30_000,
  })

  const queue = queueData?.queue || []
  const validated = queueData?.validated_count || 0
  const totalPending = queueData?.total_pending || 0

  const activeDoc = queue[activeDocIdx] || null
  const docId = activeDoc?.id
  const pred = docId ? predictions[docId] : null

  // Auto-predict when active doc changes
  useEffect(() => {
    if (!docId || predictions[docId] !== undefined) return
    setPredictions((p) => ({ ...p, [docId]: null })) // null = loading

    llmPredict(projectId, docId)
      .then((result) => setPredictions((p) => ({ ...p, [docId]: result })))
      .catch((err) => setPredictions((p) => ({ ...p, [docId]: { error: err.message, label: 'unknown', confidence: 0.5 } })))
  }, [docId, projectId])

  function showToast(msg, type = 'success') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const { mutate: decide, isPending: isSaving } = useMutation({
    mutationFn: ({ label }) => recordDecision(projectId, docId, {
      human_label: label,
      human_reason: humanReason || null,
      reason_code: reasonCode === '(none)' ? null : reasonCode,
      is_protocol_specific: true,
      reviewer: reviewer || null,
      llm_label: pred?.label || null,
      llm_confidence: pred?.confidence || null,
      llm_reasoning: pred?.reasoning || null,
    }),
    onSuccess: (_, { label }) => {
      qc.invalidateQueries({ queryKey: ['screening-queue', projectId] })
      qc.invalidateQueries({ queryKey: ['screening-stats', projectId] })
      const newCount = sessionDecisions + 1
      setSessionDecisions(newCount)
      // Flash "pattern learned" every time threshold of 3 is crossed
      if (newCount % 3 === 0) setLastLearnedAt(Date.now())
      showToast(`${label === 'include' ? '✅' : '❌'} ${label.toUpperCase()} saved`)
      // Advance to next doc
      refetchQueue().then(({ data }) => {
        const newQueue = data?.queue || []
        const nextIdx = Math.min(activeDocIdx, Math.max(0, newQueue.length - 1))
        setActiveDocIdx(nextIdx)
      })
      setHumanReason('')
      setReasonCode('(none)')
      setShowAnnotation(false)
    },
    onError: (e) => showToast(e.message, 'error'),
  })

  // Keyboard shortcuts
  useEffect(() => {
    function handler(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      if (e.key === 'i') decide({ label: 'include' })
      if (e.key === 'e') decide({ label: 'exclude' })
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault()
        setActiveDocIdx((i) => Math.min(i + 1, queue.length - 1))
      }
      if (e.key === 'ArrowLeft') {
        setActiveDocIdx((i) => Math.max(i - 1, 0))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [decide, queue.length])

  const parsed = parseDoc(activeDoc?.content || '')
  const title = parsed.Title || activeDoc?.source_id || (activeDoc?.id?.slice(0, 16) ?? '—')
  const abstract = parsed.Abstract || ''
  const authors = parsed.Authors || ''
  const journal = parsed.Journal || ''
  const year = parsed.Year || ''
  const doi = parsed.DOI || ''

  const total = validated + totalPending
  const progress = total > 0 ? Math.min(validated / total, 1) : 0

  return (
    <div className="h-full flex flex-col">
      {/* Progress header */}
      <div className="px-6 py-3 border-b border-slate-200 bg-white shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-sm font-semibold text-slate-900">
            Screening — Human Validation Loop
          </h1>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="font-medium text-slate-700">{validated}</span> validated ·
            <span className="font-medium text-slate-700">{totalPending}</span> pending
            <span className="text-slate-300 mx-1">·</span>
            <kbd className="bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded text-[10px] font-mono">I</kbd> include
            <kbd className="bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded text-[10px] font-mono">E</kbd> exclude
          </div>
        </div>
        <div className="bg-slate-100 rounded-full h-1.5">
          <div
            className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      </div>

      {/* Three-panel body */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT: Queue + Stats */}
        <div className="w-60 shrink-0 border-r border-slate-200 bg-white flex flex-col">
          <div className="flex border-b border-slate-200">
            <button
              className={`flex-1 py-2.5 text-xs font-medium transition-colors
                ${activeTab === 'queue' ? 'text-blue-600 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-700'}`}
              onClick={() => setActiveTab('queue')}
            >
              Queue ({queue.length})
            </button>
            <button
              className={`flex-1 py-2.5 text-xs font-medium transition-colors
                ${activeTab === 'stats' ? 'text-blue-600 border-b-2 border-blue-500' : 'text-slate-500 hover:text-slate-700'}`}
              onClick={() => setActiveTab('stats')}
            >
              <BarChart2 size={11} className="inline mr-1" />Stats
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {activeTab === 'queue' && (
              queueLoading ? (
                <div className="flex justify-center py-8"><LoadingSpinner /></div>
              ) : queue.length === 0 ? (
                <div className="text-center py-12 text-slate-400 px-4">
                  <CheckCircle size={28} className="mx-auto mb-2 text-emerald-400" />
                  <p className="text-sm font-medium">All done!</p>
                </div>
              ) : (
                queue.map((doc, i) => (
                  <QueueItem
                    key={doc.id}
                    doc={doc}
                    isActive={i === activeDocIdx}
                    onClick={() => setActiveDocIdx(i)}
                  />
                ))
              )
            )}
            {activeTab === 'stats' && <StatsView projectId={projectId} />}
          </div>
        </div>

        {/* CENTER: Paper */}
        <div className="flex-1 overflow-y-auto bg-slate-50">
          {!activeDoc ? (
            <div className="flex items-center justify-center h-full text-slate-400">
              <div className="text-center">
                <BookOpen size={40} className="mx-auto mb-3 opacity-30" />
                <p>Select a paper from the queue</p>
              </div>
            </div>
          ) : (
            <div className="max-w-2xl mx-auto px-6 py-6">
              {/* Nav */}
              <div className="flex items-center justify-between mb-4">
                <button
                  className="btn-secondary text-xs"
                  disabled={activeDocIdx === 0}
                  onClick={() => setActiveDocIdx((i) => Math.max(i - 1, 0))}
                >
                  ← Prev
                </button>
                <span className="text-xs text-slate-500">
                  Paper <strong>{activeDocIdx + 1}</strong> of <strong>{queue.length}</strong>
                  <span className="text-slate-300 mx-1.5">·</span>
                  ranked by uncertainty
                </span>
                <button
                  className="btn-secondary text-xs"
                  disabled={activeDocIdx >= queue.length - 1}
                  onClick={() => setActiveDocIdx((i) => Math.min(i + 1, queue.length - 1))}
                >
                  Next →
                </button>
              </div>

              {/* AL pre-rank badge */}
              {activeDoc.al_label && activeDoc.al_label !== 'unknown' && (
                <div className="flex items-center gap-1.5 mb-3">
                  <Badge color={activeDoc.al_label === 'include' ? 'green' : 'red'}>
                    AL: {activeDoc.al_label.toUpperCase()} {Math.round((activeDoc.al_confidence || 0) * 100)}%
                  </Badge>
                  <span className="text-[10px] text-slate-400">Active Learning pre-rank</span>
                </div>
              )}

              {/* Paper content */}
              <div className="card px-6 py-5">
                <h2 className="text-base font-semibold text-slate-900 leading-snug mb-2">{title}</h2>
                {(authors || journal || year) && (
                  <p className="text-xs text-slate-500 mb-1">
                    {[authors.slice(0, 80), journal, year].filter(Boolean).join(' · ')}
                  </p>
                )}
                {doi && (
                  <p className="text-xs font-mono text-slate-400 mb-3">DOI: {doi}</p>
                )}
                <hr className="border-slate-100 mb-4" />
                {abstract ? (
                  <p className="text-sm text-slate-700 leading-relaxed">{abstract}</p>
                ) : (
                  <p className="text-sm text-slate-400 italic">No abstract available</p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: LLM Panel */}
        <div className="w-72 shrink-0 border-l border-slate-200 bg-white flex flex-col">
          <div className="shrink-0">
            <div className="panel-header">
              <div className="flex items-center gap-1.5">
                <Brain size={14} className="text-purple-500" />
                <span className="text-sm font-semibold text-slate-700">AI Assessment</span>
              </div>
              {pred && (
                <button
                  className="text-xs text-slate-400 hover:text-slate-600 flex items-center gap-1"
                  onClick={() => {
                    setPredictions((p) => {
                      const copy = { ...p }
                      delete copy[docId]
                      return copy
                    })
                  }}
                >
                  <RotateCcw size={11} /> Re-predict
                </button>
              )}
            </div>

            {/* HITL memory indicator — visible feedback that decisions teach the model */}
            {(sessionDecisions > 0 || validated > 0) && (() => {
              const isFlashing = lastLearnedAt && (Date.now() - lastLearnedAt) < 5000
              return (
                <div className={`px-3 py-2 border-b border-slate-100 flex items-center gap-2 text-xs
                  transition-colors duration-700 ${isFlashing ? 'bg-amber-50' : 'bg-slate-50'}`}>
                  <Sparkles size={12} className={isFlashing ? 'text-amber-500 animate-pulse' : 'text-slate-400'} />
                  <div className="flex-1 leading-tight">
                    <span className="font-medium text-slate-700">{validated + sessionDecisions}</span>
                    <span className="text-slate-400"> examples in memory</span>
                    {isFlashing && <span className="ml-1 text-amber-600 font-medium">· pattern learned</span>}
                  </div>
                  {sessionDecisions > 0 && (
                    <span className="text-emerald-600 font-semibold">+{sessionDecisions}</span>
                  )}
                </div>
              )
            })()}
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {!activeDoc && (
              <p className="text-xs text-slate-400 italic">Select a paper to see the LLM assessment.</p>
            )}

            {activeDoc && pred === null && (
              <div className="flex flex-col items-center py-6 gap-2 text-slate-500">
                <LoadingSpinner size="md" />
                <p className="text-xs">Running few-shot prediction…</p>
                <p className="text-[10px] text-slate-400">Loading similar examples from decision memory</p>
              </div>
            )}

            {pred?.error && (
              <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-600">
                {pred.error}
              </div>
            )}

            {pred && !pred.error && (
              <>
                {/* Confidence */}
                <ConfidenceBar label={pred.label} confidence={pred.confidence} />

                {/* Reasoning */}
                {pred.reasoning && (
                  <div>
                    <p className="text-xs font-medium text-slate-600 mb-1">Reasoning</p>
                    <p className="text-xs text-slate-600 leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-100">
                      {pred.reasoning}
                    </p>
                  </div>
                )}

                {/* Guidance applied */}
                {pred.guidance_applied && (
                  <div className="flex items-center gap-1.5 text-xs text-purple-600 bg-purple-50 rounded-lg px-2.5 py-1.5 border border-purple-100">
                    <Lightbulb size={11} />
                    Reviewer preferences applied
                  </div>
                )}

                {/* Similar examples */}
                {pred.similar_examples?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-slate-600 mb-1.5 flex items-center gap-1">
                      <Users size={11} />
                      {pred.similar_examples.length} similar validated examples
                    </p>
                    <div className="space-y-1.5">
                      {pred.similar_examples.map((ex, i) => (
                        <SimilarExample key={i} ex={ex} />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Decision panel */}
          {activeDoc && (
            <div className="p-4 border-t border-slate-200 space-y-3">
              <p className="text-xs font-semibold text-slate-700">Your Decision</p>

              <div className="grid grid-cols-2 gap-2">
                <button
                  className="btn-success justify-center py-2.5"
                  onClick={() => decide({ label: 'include' })}
                  disabled={isSaving || !activeDoc}
                  title="Shortcut: I"
                >
                  {isSaving ? <LoadingSpinner size="sm" /> : <CheckCircle size={15} />}
                  Include
                </button>
                <button
                  className="btn-danger justify-center py-2.5"
                  onClick={() => decide({ label: 'exclude' })}
                  disabled={isSaving || !activeDoc}
                  title="Shortcut: E"
                >
                  {isSaving ? <LoadingSpinner size="sm" /> : <XCircle size={15} />}
                  Exclude
                </button>
              </div>

              <button
                className="w-full text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1 justify-center"
                onClick={() => setShowAnnotation((o) => !o)}
              >
                {showAnnotation ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                Add reason / note
              </button>

              {showAnnotation && (
                <div className="space-y-2 border-t border-slate-100 pt-2">
                  <div>
                    <label className="label">Reason code</label>
                    <select
                      className="input text-xs"
                      value={reasonCode}
                      onChange={(e) => setReasonCode(e.target.value)}
                    >
                      <option value="(none)">(none)</option>
                      {REASON_CODES.map((rc) => (
                        <option key={rc} value={rc}>{REASON_LABELS[rc]}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="label">Free-text note</label>
                    <textarea
                      className="textarea text-xs"
                      rows={2}
                      placeholder="e.g. Greenhouse experiment only"
                      value={humanReason}
                      onChange={(e) => setHumanReason(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="label">Reviewer ID</label>
                    <input
                      className="input text-xs"
                      placeholder="Optional"
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Export panel — fixed at bottom of right panel */}
      {validated > 0 && (
        <div className="shrink-0 border-t border-slate-200 bg-white">
          <button
            className="w-full px-3 py-2 flex items-center justify-between text-xs text-slate-600 hover:bg-slate-50 transition-colors"
            onClick={() => setShowExport((o) => !o)}
          >
            <div className="flex items-center gap-1.5">
              <Download size={12} />
              <span className="font-medium">Export {validated} validated decisions</span>
            </div>
            <ChevronDown size={12} className={`transition-transform ${showExport ? 'rotate-180' : ''}`} />
          </button>

          {showExport && (
            <div className="px-3 pb-3 space-y-2 border-t border-slate-100 pt-2">
              {/* CSV / Excel direct downloads */}
              <div className="grid grid-cols-2 gap-1.5">
                <a
                  href={exportCsvUrl(projectId)}
                  download
                  className="btn-secondary justify-center text-xs py-1.5"
                >
                  <FileSpreadsheet size={12} /> CSV
                </a>
                <a
                  href={exportExcelUrl(projectId)}
                  download
                  className="btn-secondary justify-center text-xs py-1.5"
                >
                  <FileSpreadsheet size={12} /> Excel
                </a>
              </div>

              {/* Google Sheets */}
              <div className="space-y-1.5">
                <label className="label text-xs mb-0">Google Sheets (paste sheet URL or leave blank to create new)</label>
                <input
                  className="input text-xs py-1"
                  placeholder="https://docs.google.com/spreadsheets/d/…"
                  value={sheetsId}
                  onChange={(e) => setSheetsId(e.target.value)}
                />
                <button
                  className="btn-primary w-full justify-center text-xs py-1.5"
                  disabled={sheetsExporting}
                  onClick={async () => {
                    setSheetsExporting(true)
                    setSheetsResult(null)
                    try {
                      const match = sheetsId.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
                      const res = await exportGoogleSheets(projectId, {
                        spreadsheet_id: match ? match[1] : '',
                        sheet_name: 'Validated Papers',
                      })
                      setSheetsResult({ ok: true, url: res.sheet_url, rows: res.rows_written })
                    } catch (e) {
                      setSheetsResult({ ok: false, msg: e.message })
                    }
                    setSheetsExporting(false)
                  }}
                >
                  {sheetsExporting ? <LoadingSpinner size="sm" /> : <Sheet size={12} />}
                  Push to Google Sheets
                </button>
                {sheetsResult?.ok && (
                  <a href={sheetsResult.url} target="_blank" rel="noopener noreferrer"
                    className="block text-xs text-center text-emerald-600 hover:underline">
                    ✓ {sheetsResult.rows} rows written — open sheet ↗
                  </a>
                )}
                {sheetsResult && !sheetsResult.ok && (
                  <p className="text-xs text-red-500">{sheetsResult.msg}</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2.5 rounded-xl shadow-lg text-sm font-medium z-50
          ${toast.type === 'error' ? 'bg-red-600 text-white' : 'bg-slate-900 text-white'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
