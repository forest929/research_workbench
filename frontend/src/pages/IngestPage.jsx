import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchIngestStatus, triggerAnalyze, fetchAnalyzeStatus } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { Database, CheckCircle2, AlertCircle, ArrowRight, Loader2, FileWarning, FlaskConical, Microscope } from 'lucide-react'

const INGEST_ACTIVE = ['running', 'embedding']
const ANALYZE_ACTIVE = ['running']
const PHASE_LABEL = {
  extracting: 'Extracting claims from documents',
  embedding: 'Embedding claims',
  clustering: 'Clustering claims across papers',
  synthesizing: 'Synthesizing cited answers',
  finalizing: 'Laying out the evidence map',
}

function Stat({ label, value }) {
  return (
    <div className="px-3.5 py-2.5 rounded-lg bg-white border border-slate-200 text-center">
      <p className="text-[10px] uppercase tracking-wide text-slate-400 leading-none">{label}</p>
      <p className="text-lg font-semibold text-slate-800 mt-1 tabular-nums">{value ?? 0}</p>
    </div>
  )
}

function Bar({ pct, done }) {
  return (
    <div className="h-2 rounded-full bg-slate-200 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${done ? 'bg-emerald-500' : 'bg-blue-500'}`}
        style={{ width: `${done ? 100 : pct}%` }}
      />
    </div>
  )
}

/**
 * Post-create pipeline screen: (1) ingest documents, then (2) analyze them into
 * claims/clusters/answers. Polls both statuses and hands off to the workbench.
 */
export default function IngestPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: ing } = useQuery({
    queryKey: ['ingestStatus', projectId],
    queryFn: () => fetchIngestStatus(projectId),
    refetchInterval: (q) => (INGEST_ACTIVE.includes(q.state.data?.status) ? 1500 : false),
  })
  const { data: ana } = useQuery({
    queryKey: ['analyzeStatus', projectId],
    queryFn: () => fetchAnalyzeStatus(projectId),
    refetchInterval: (q) => (ANALYZE_ACTIVE.includes(q.state.data?.status) ? 2000 : false),
  })

  const analyze = useMutation({
    mutationFn: () => triggerAnalyze(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analyzeStatus', projectId] }),
  })

  const iStatus = ing?.status || 'idle'
  const iActive = INGEST_ACTIVE.includes(iStatus)
  const iTotal = ing?.total || 0
  const iDone = iStatus === 'embedding' ? ing?.embedded : ing?.ingested
  const iPct = iTotal ? Math.min(100, Math.round(((iDone || 0) / iTotal) * 100)) : (iActive ? 5 : 0)
  const ingestDone = iStatus === 'done'

  const aStatus = ana?.status || 'idle'
  const aActive = ANALYZE_ACTIVE.includes(aStatus)
  const aPhase = ana?.phase
  const aPct =
    aStatus === 'done' ? 100
      : aPhase === 'extracting' && ana?.docs_total ? Math.round((ana.docs_done / ana.docs_total) * 100)
      : aPhase === 'synthesizing' && ana?.conversations_total ? Math.round((ana.conversations_done / ana.conversations_total) * 100)
      : aActive ? 60 : 0

  const workbench = () => navigate(`/projects/${projectId}`)

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      <div className="max-w-xl mx-auto px-6 py-10 space-y-6">

        {/* ── Step 1: ingest ── */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${ingestDone ? 'bg-emerald-100' : iStatus === 'error' ? 'bg-amber-100' : 'bg-blue-100'}`}>
              {ingestDone ? <CheckCircle2 size={18} className="text-emerald-600" />
                : iStatus === 'error' ? <AlertCircle size={18} className="text-amber-600" />
                : <Database size={17} className="text-blue-600" />}
            </div>
            <div>
              <h2 className="text-sm font-semibold text-slate-800 leading-none">1 · Import documents</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {ingestDone ? `${ing?.db_total || 0} documents in this project`
                  : iStatus === 'error' ? (ing?.error || 'Import problem')
                  : iStatus === 'idle' ? 'No import running'
                  : 'Importing…'}
              </p>
            </div>
          </div>
          {(iActive || ingestDone) && (
            <div className="mb-3">
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span className="flex items-center gap-1.5">
                  {iActive && <Loader2 size={12} className="animate-spin text-blue-500" />}
                  {ingestDone ? 'Complete' : (iStatus === 'embedding' ? 'Embedding…' : 'Ingesting…')}
                </span>
                <span className="tabular-nums">{iPct}%</span>
              </div>
              <Bar pct={iPct} done={ingestDone} />
            </div>
          )}
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Fetched" value={ing?.fetched} />
            <Stat label="Ingested" value={ing?.ingested} />
            <Stat label="Documents" value={ing?.db_total} />
          </div>
          {ing?.skipped?.length > 0 && (
            <div className="mt-3 flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <FileWarning size={14} className="shrink-0 mt-0.5" />
              <span>Skipped {ing.skipped.length} file(s) with no extractable content.</span>
            </div>
          )}
          {/* Per-DOI resolution report — which DOIs resolved and which were skipped, and why */}
          {ing?.results?.length > 0 && (() => {
            const REASON = {
              no_abstract: 'resolved but no abstract to ingest',
              unresolved: 'not found on PubMed or Crossref',
              duplicate: 'duplicate of another source',
            }
            const resolved = ing.results.filter((r) => r.status === 'resolved')
            const skipped = ing.results.filter((r) => r.status !== 'resolved')
            return (
              <div className="mt-3 text-xs">
                <div className="flex items-center gap-1.5 text-slate-600 mb-1.5">
                  <CheckCircle2 size={13} className="text-emerald-600 shrink-0" />
                  <span>
                    {resolved.length} of {ing.results.length} DOIs resolved
                    {skipped.length > 0 ? `, ${skipped.length} skipped` : ''}
                  </span>
                </div>
                {skipped.length > 0 && (
                  <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                    {skipped.map((r) => (
                      <li key={r.doi} className="flex items-start gap-1.5 text-amber-800">
                        <AlertCircle size={12} className="shrink-0 mt-0.5" />
                        <span className="font-mono break-all">{r.doi}</span>
                        <span className="text-amber-600 whitespace-nowrap">— {REASON[r.status] || r.status}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })()}
        </section>

        {/* ── Step 2: analyze ── */}
        <section className={`rounded-xl border p-4 ${ingestDone || aStatus !== 'idle' ? 'border-slate-200 bg-white' : 'border-dashed border-slate-200 bg-slate-50 opacity-70'}`}>
          <div className="flex items-center gap-2 mb-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${aStatus === 'done' ? 'bg-emerald-100' : aStatus === 'error' ? 'bg-amber-100' : 'bg-violet-100'}`}>
              {aStatus === 'done' ? <CheckCircle2 size={18} className="text-emerald-600" />
                : aStatus === 'error' ? <AlertCircle size={18} className="text-amber-600" />
                : <FlaskConical size={17} className="text-violet-600" />}
            </div>
            <div>
              <h2 className="text-sm font-semibold text-slate-800 leading-none">2 · Analyze into evidence</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {aStatus === 'done' ? `${ana?.db_clusters || 0} clusters · ${ana?.db_answered || 0} answers`
                  : aStatus === 'error' ? (ana?.error || 'Analysis problem')
                  : aActive ? (PHASE_LABEL[aPhase] || 'Analyzing…')
                  : 'Extract claims → cluster → synthesize cited answers'}
              </p>
            </div>
          </div>

          {aActive && (
            <>
              <div className="mb-3">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin text-violet-500" /> {PHASE_LABEL[aPhase] || 'Working…'}</span>
                  <span className="tabular-nums">{aPct}%</span>
                </div>
                <Bar pct={aPct} />
              </div>
              <div className="grid grid-cols-4 gap-2">
                <Stat label="Docs" value={`${ana?.docs_done ?? 0}/${ana?.docs_total ?? 0}`} />
                <Stat label="Claims" value={ana?.claims_extracted} />
                <Stat label="Clusters" value={ana?.clusters_built} />
                <Stat label="Answers" value={`${ana?.conversations_done ?? 0}/${ana?.conversations_total ?? 0}`} />
              </div>
            </>
          )}

          {/* Trigger button — enabled once documents exist and analysis isn't running */}
          {!aActive && aStatus !== 'done' && (
            <button
              onClick={() => analyze.mutate()}
              disabled={!ingestDone || analyze.isPending}
              className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-violet-600 text-white
                         text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {analyze.isPending ? <Loader2 size={15} className="animate-spin" /> : <FlaskConical size={15} />}
              {aStatus === 'error' ? 'Retry analysis' : 'Run analysis'}
            </button>
          )}
          {!ingestDone && aStatus === 'idle' && (
            <p className="text-center text-[11px] text-slate-400 mt-2">Waiting for import to finish…</p>
          )}
          <p className="text-[11px] text-slate-400 mt-2 text-center">
            Makes LLM + embedding calls — needs a valid <code className="bg-slate-100 px-1 rounded">NEBIUS_KEY</code> and embedding endpoint.
          </p>
        </section>

        {/* ── Continue ── */}
        <div className="flex justify-center">
          <button
            onClick={workbench}
            className={`inline-flex items-center gap-1.5 px-5 py-2.5 rounded-lg text-sm font-medium ${
              aStatus === 'done' ? 'bg-blue-600 text-white hover:bg-blue-700' : 'border border-slate-300 text-slate-600 hover:bg-white'
            }`}
          >
            <Microscope size={15} /> {aStatus === 'done' ? 'Open workbench' : 'Go to workbench'}
            <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}
