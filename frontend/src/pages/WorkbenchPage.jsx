import { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchProject, fetchClusters, fetchClusterStats, fetchClusterDetail, fetchWorkbenchOptions, saveFilteredPapers,
  fetchIngestStatus, fetchAnalyzeStatus, triggerAnalyze, cancelBuild, askAssistant, fetchAssistantHistory,
} from '../api'
import ClusterMap from '../components/ClusterMap'
import ConversationPanel from '../components/ConversationPanel'
import PapersPanel from '../components/PapersPanel'
import ReadingListPanel from '../components/ReadingListPanel'
import SearchableSelect from '../components/SearchableSelect'
import DiseaseVocabEditor from '../components/DiseaseVocabEditor'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  ArrowLeft, X, Filter, Tag, BookmarkPlus, Check, Loader2, Network,
  PanelLeft, PanelRight, Sparkles, History,
} from 'lucide-react'

const ACTIVE = ['running', 'ingesting', 'embedding', 'extracting', 'clustering', 'synthesizing', 'finalizing', 'started']

export default function WorkbenchPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()

  const [selected, setSelected] = useState(null)
  const [drug, setDrug] = useState('')
  const [disease, setDisease] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [locatedIds, setLocatedIds] = useState([])
  const [editingVocab, setEditingVocab] = useState(false)
  const [askText, setAskText] = useState('')
  const [assistantResult, setAssistantResult] = useState(null)
  const [showHistory, setShowHistory] = useState(false)

  // Resizable / collapsible panes
  const [leftW, setLeftW] = useState(288)
  const [rightW, setRightW] = useState(320)
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [answerH, setAnswerH] = useState(360)

  const beginResize = (e, axis, base, setter, min, max, sign) => {
    e.preventDefault()
    const start = axis === 'x' ? e.clientX : e.clientY
    const onMove = (ev) => {
      const pos = axis === 'x' ? ev.clientX : ev.clientY
      setter(Math.max(min, Math.min(max, base + sign * (pos - start))))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
  }

  const { data: project } = useQuery({ queryKey: ['project', projectId], queryFn: () => fetchProject(projectId) })
  const { data: clustersData, isLoading: clustersLoading } = useQuery({
    queryKey: ['clusters', projectId], queryFn: () => fetchClusters(projectId, true),
  })
  const { data: stats } = useQuery({ queryKey: ['clusterStats', projectId], queryFn: () => fetchClusterStats(projectId) })
  const { data: options } = useQuery({ queryKey: ['workbenchOptions', projectId], queryFn: () => fetchWorkbenchOptions(projectId) })
  const { data: detail, isLoading: detailLoading, isFetching: detailFetching } = useQuery({
    queryKey: ['clusterDetail', projectId, selected?.id, showAll],
    queryFn: () => fetchClusterDetail(projectId, selected.id, showAll),
    enabled: !!selected?.id,
  })

  // ── Pipeline, hidden behind one "building" state ──
  const { data: ing } = useQuery({
    queryKey: ['ingestStatus', projectId], queryFn: () => fetchIngestStatus(projectId),
    refetchInterval: (q) => (ACTIVE.includes(q.state.data?.status) ? 1500 : false),
  })
  const { data: ana } = useQuery({
    queryKey: ['analyzeStatus', projectId], queryFn: () => fetchAnalyzeStatus(projectId),
    refetchInterval: (q) => (ACTIVE.includes(q.state.data?.status) ? 2000 : false),
  })
  const analyze = useMutation({
    mutationFn: () => triggerAnalyze(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analyzeStatus', projectId] }),
  })
  const cancel = useMutation({
    mutationFn: () => cancelBuild(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analyzeStatus', projectId] })
      qc.invalidateQueries({ queryKey: ['ingestStatus', projectId] })
    },
  })

  const clusters = clustersData?.clusters || []
  const docsReady = (ing?.db_total || 0) > 0
  const ingestActive = ACTIVE.includes(ing?.status)
  const analyzeActive = ACTIVE.includes(ana?.status)
  const analyzed = (ana?.db_clusters ?? stats?.total_clusters ?? 0) > 0 || clusters.length > 0
  const cancelled = ing?.status === 'cancelled' || ana?.status === 'cancelled'

  const kicked = useRef(false)
  useEffect(() => {
    if (!kicked.current && docsReady && !ingestActive && !analyzeActive && !analyzed
        && ana?.status !== 'error' && !cancelled && !analyze.isPending) {
      kicked.current = true
      analyze.mutate()
    }
  }, [docsReady, ingestActive, analyzeActive, analyzed, ana?.status, cancelled])

  const prevAna = useRef(ana?.status)
  useEffect(() => {
    if (prevAna.current && prevAna.current !== 'done' && ana?.status === 'done') {
      qc.invalidateQueries({ queryKey: ['clusters', projectId] })
      qc.invalidateQueries({ queryKey: ['clusterStats', projectId] })
      qc.invalidateQueries({ queryKey: ['workbenchOptions', projectId] })
    }
    prevAna.current = ana?.status
  }, [ana?.status])

  const pipelineSettled = ana?.status === 'done' || ana?.status === 'error' || cancelled
  const building = !analyzed && !pipelineSettled && (ingestActive || analyzeActive || analyze.isPending || docsReady)

  useEffect(() => { setShowAll(false) }, [selected?.id])
  useEffect(() => {
    setSelected(null); setDrug(''); setDisease(''); setLocatedIds([]); setEditingVocab(false); setAssistantResult(null)
  }, [projectId])
  useEffect(() => {
    const c = searchParams.get('cluster')
    if (c) { setSelected({ id: c }); setLocatedIds([c]) }
  }, [projectId, searchParams])

  const prettyDrug = (k) => k.replace(/\b\w/g, (m) => m.toUpperCase())
  const hasFilter = Boolean(drug || disease)
  const clearFilter = () => { setDrug(''); setDisease('') }

  // Cross-filtered filter counts: when a disease is picked, the drug counts show
  // only that disease's papers (the intersection), and vice versa.
  const drugOptions = useMemo(() => {
    const counts = {}
    for (const c of clusters) {
      if (disease && !(c.diseases || []).includes(disease)) continue
      if (!c.intervention_key) continue
      counts[c.intervention_key] = (counts[c.intervention_key] || 0) + (c.member_count || 0)
    }
    return Object.entries(counts)
      .map(([key, count]) => ({ key, label: prettyDrug(key), count }))
      .sort((a, b) => b.count - a.count)
  }, [clusters, disease])
  // If a disease is picked and the current drug isn't associated with it, clear
  // the drug so the two filters stay consistent.
  useEffect(() => {
    if (drug && !drugOptions.some((o) => o.key === drug)) setDrug('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disease])

  const diseaseLabels = useMemo(
    () => Object.fromEntries((options?.diseases || []).map((d) => [d.key, d.label])), [options])
  const diseaseOptions = useMemo(() => {
    const counts = {}
    for (const c of clusters) {
      if (drug && c.intervention_key !== drug) continue
      for (const ds of (c.diseases || [])) counts[ds] = (counts[ds] || 0) + 1
    }
    return Object.entries(counts)
      .map(([key, count]) => ({ key, label: diseaseLabels[key] || key, count }))
      .sort((a, b) => b.count - a.count)
  }, [clusters, drug, diseaseLabels])

  // Assistant Q&A history.
  const { data: history } = useQuery({
    queryKey: ['assistantHistory', projectId],
    queryFn: () => fetchAssistantHistory(projectId),
    enabled: !!projectId,
  })
  const historyItems = history?.items || []

  const saveAll = useMutation({
    mutationFn: () => saveFilteredPapers(projectId, { drug: drug || null, disease: disease || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['readingList', projectId] }),
  })
  useEffect(() => { saveAll.reset() }, [drug, disease])

  // Research-assistant agent: ask a free-form question over the corpus.
  const ask = useMutation({
    mutationFn: (q) => askAssistant(projectId, q),
    onSuccess: (res) => { setAssistantResult(res); qc.invalidateQueries({ queryKey: ['assistantHistory', projectId] }) },
  })
  const openHistory = (item) => { setSelected(null); setAssistantResult(item); setShowHistory(false) }
  const submitAsk = (e) => {
    e.preventDefault()
    const q = askText.trim()
    if (!q) return
    setSelected(null); setAssistantResult(null); ask.mutate(q)
  }

  const locate = (ids) => { if (ids?.length) { setAssistantResult(null); setLocatedIds(ids); setSelected({ id: ids[0] }) } }
  const selectCluster = (c) => { setAssistantResult(null); setSelected(c) }

  const panelDetail = assistantResult || detail
  const panelOpen = (assistantResult || selected || ask.isPending) && !building

  const Divider = ({ onMouseDown, axis }) => (
    <div
      onMouseDown={onMouseDown}
      className={`shrink-0 ${axis === 'x' ? 'w-1 cursor-col-resize' : 'h-1 cursor-row-resize'} bg-slate-200 hover:bg-blue-400 transition-colors`}
    />
  )

  return (
    <div className="h-screen flex flex-col bg-white">
      {/* Top bar */}
      <header className="h-14 shrink-0 border-b border-slate-200 flex items-center gap-3 px-4">
        <button onClick={() => navigate('/')} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800">
          <ArrowLeft size={16} /> Projects
        </button>
        <span className="text-slate-200">/</span>
        <span className="font-display text-[15px] text-slate-800 truncate max-w-md">{project?.name || 'Review'}</span>
        {building && (
          <span className="ml-2 inline-flex items-center gap-1.5 text-xs text-blue-600">
            <Loader2 size={12} className="animate-spin" /> Building evidence base…
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => setLeftOpen((v) => !v)} title={leftOpen ? 'Hide papers' : 'Show papers'}
            className={`p-1.5 rounded-lg transition-colors ${leftOpen ? 'text-blue-600 bg-blue-50' : 'text-slate-400 hover:bg-slate-100'}`}>
            <PanelLeft size={16} />
          </button>
          <button onClick={() => setRightOpen((v) => !v)} title={rightOpen ? 'Hide reading list' : 'Show reading list'}
            className={`p-1.5 rounded-lg transition-colors ${rightOpen ? 'text-blue-600 bg-blue-50' : 'text-slate-400 hover:bg-slate-100'}`}>
            <PanelRight size={16} />
          </button>
        </div>
      </header>

      {/* 3-pane console */}
      <div className="flex-1 min-h-0 flex">
        {leftOpen && (
          <>
            <aside style={{ width: leftW }} className="shrink-0 bg-white overflow-hidden">
              <PapersPanel projectId={projectId} onLocate={(ids) => locate(ids)} />
            </aside>
            <Divider axis="x" onMouseDown={(e) => beginResize(e, 'x', leftW, setLeftW, 200, 520, 1)} />
          </>
        )}

        {/* Center */}
        <main className="flex-1 min-w-0 flex flex-col bg-slate-50">
          {/* Ask the evidence — research-assistant agent */}
          <div className="shrink-0 border-b border-slate-200 bg-white relative">
            <form onSubmit={submitAsk} className="px-3 py-2 flex items-center gap-2">
              <Sparkles size={16} className="text-blue-500 shrink-0" />
              <input
                value={askText}
                onChange={(e) => setAskText(e.target.value)}
                placeholder="Ask the evidence — “compare drug A vs B”, “what contradicts the majority view”, “where are the gaps?”"
                className="flex-1 min-w-0 px-2 py-1.5 text-sm bg-transparent focus:outline-none placeholder:text-slate-400"
              />
              {historyItems.length > 0 && (
                <button type="button" onClick={() => setShowHistory((v) => !v)} title="Past questions"
                  className={`shrink-0 inline-flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs ${showHistory ? 'bg-blue-50 text-blue-600' : 'text-slate-500 hover:bg-slate-100'}`}>
                  <History size={14} /> {historyItems.length}
                </button>
              )}
              <button type="submit" disabled={ask.isPending || !askText.trim()}
                className="shrink-0 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
                {ask.isPending ? <><Loader2 size={12} className="animate-spin" /> Asking…</> : 'Ask'}
              </button>
            </form>
            {showHistory && historyItems.length > 0 && (
              <div className="absolute z-20 right-2 top-full mt-1 w-96 max-h-80 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg py-1">
                <p className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-400">Past questions</p>
                {historyItems.map((h) => (
                  <button key={h.id} onClick={() => openHistory(h)}
                    className="w-full text-left px-3 py-2 hover:bg-slate-50">
                    <p className="text-[13px] text-slate-800 line-clamp-2">{h.question}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      {h.judge?.verdict ? `judge: ${h.judge.verdict} · ` : ''}{h.distinct_document_count} sources
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="shrink-0 border-b border-slate-200 bg-white px-3 py-2 flex items-center gap-2 flex-wrap">
            <SearchableSelect value={drug} onChange={setDrug} placeholder="All drugs" options={drugOptions} />
            <select value={disease} onChange={(e) => setDisease(e.target.value)}
              className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white">
              <option value="">All diseases</option>
              {diseaseOptions.map((d) => <option key={d.key} value={d.key}>{d.label} ({d.count})</option>)}
            </select>
            <button onClick={() => setEditingVocab(true)} title="Edit diseases"
              className="inline-flex items-center gap-1 px-2.5 py-2 rounded-lg border border-slate-200 text-slate-500 text-xs hover:bg-slate-50">
              <Tag size={12} /> Diseases
            </button>
            {hasFilter && (
              <>
                <button onClick={() => saveAll.mutate()} disabled={saveAll.isPending}
                  className="inline-flex items-center gap-1 px-2.5 py-2 rounded-lg border border-blue-300 text-blue-600 bg-white text-xs hover:bg-blue-50 disabled:opacity-60">
                  {saveAll.isPending ? <><Loader2 size={12} className="animate-spin" /> Saving…</>
                    : saveAll.isSuccess ? <><Check size={12} /> Saved {saveAll.data?.saved}</>
                    : <><BookmarkPlus size={12} /> Save all papers</>}
                </button>
                <button onClick={clearFilter} className="inline-flex items-center gap-1 px-2.5 py-2 rounded-lg border border-slate-200 text-slate-500 text-xs hover:bg-slate-50">
                  <X size={12} /> Clear
                </button>
              </>
            )}
          </div>

          <div className="flex-1 min-h-0 flex flex-col">
            <div className="flex-1 min-h-0 relative">
              {building ? (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                  <Loader2 size={28} className="mb-3 text-blue-500 animate-spin" />
                  <p className="text-sm font-medium text-slate-600">Building your evidence base</p>
                  <p className="text-xs text-slate-400 mt-1 max-w-xs">
                    Reading the papers and mapping the evidence{ing?.db_total ? ` · ${ing.db_total} papers` : ''}. This runs on its own.
                  </p>
                  <button onClick={() => cancel.mutate()} disabled={cancel.isPending}
                    className="mt-5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 text-xs hover:bg-white disabled:opacity-60">
                    {cancel.isPending ? <><Loader2 size={12} className="animate-spin" /> Cancelling…</> : <><X size={12} /> Cancel build</>}
                  </button>
                </div>
              ) : clustersLoading ? (
                <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
              ) : clusters.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-6">
                  <Network size={26} className="mb-3 opacity-40" />
                  <p className="text-sm font-medium text-slate-500">{cancelled ? 'Build cancelled' : 'No evidence map yet'}</p>
                  <p className="text-xs mt-1 max-w-xs">Add papers from the left, or start a new search from Projects.</p>
                </div>
              ) : (
                <ClusterMap
                  clusters={clusters} selectedId={selected?.id} onSelect={selectCluster}
                  highlightDrug={drug} highlightDisease={disease}
                  locatedIds={locatedIds} onClearLocated={() => setLocatedIds([])}
                />
              )}
            </div>
            {panelOpen && (
              <>
                <Divider axis="y" onMouseDown={(e) => beginResize(e, 'y', answerH, setAnswerH, 160, 680, -1)} />
                <div style={{ height: answerH }} className="shrink-0 border-t border-slate-200 bg-white overflow-hidden flex flex-col">
                  {assistantResult && (
                    <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-slate-100 bg-blue-50/40">
                      <Sparkles size={13} className="text-blue-500" />
                      <span className="text-xs font-medium text-blue-700">Assistant answer</span>
                      <button onClick={() => setAssistantResult(null)} className="ml-auto text-slate-400 hover:text-slate-600" title="Close">
                        <X size={14} />
                      </button>
                    </div>
                  )}
                  <div className="flex-1 min-h-0">
                    {ask.isPending && !assistantResult ? (
                      <div className="flex flex-col items-center justify-center h-full text-slate-400">
                        <Loader2 size={22} className="animate-spin mb-2 text-blue-500" />
                        <p className="text-sm">Reading the evidence…</p>
                      </div>
                    ) : assistantResult && !assistantResult.answer ? (
                      <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-6">
                        <p className="text-sm font-medium text-slate-500">No evidence covers that yet</p>
                        <p className="text-xs mt-1">Try rephrasing, or add more papers on the topic.</p>
                      </div>
                    ) : (
                      <ConversationPanel
                        detail={panelDetail} loading={detailLoading && !detail && !assistantResult}
                        showingAll={showAll} onToggleAll={() => setShowAll((v) => !v)} loadingMore={detailFetching}
                      />
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </main>

        {rightOpen && (
          <>
            <Divider axis="x" onMouseDown={(e) => beginResize(e, 'x', rightW, setRightW, 220, 520, -1)} />
            <aside style={{ width: rightW }} className="shrink-0 bg-white overflow-hidden">
              <ReadingListPanel projectId={projectId} onLocate={(ids) => locate(ids)} />
            </aside>
          </>
        )}
      </div>

      {editingVocab && (
        <DiseaseVocabEditor projectId={projectId} vocab={options?.vocab || {}} onClose={() => setEditingVocab(false)} />
      )}
    </div>
  )
}
