import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchProject, fetchResults, runAnalysis, approveProject, resolveProject } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import JudgeScorecard from '../components/JudgeScorecard'
import Badge from '../components/Badge'
import {
  Play, CheckCircle, AlertTriangle, ChevronDown, ChevronRight,
  Layers, BookOpen, Cpu, ShieldCheck, CheckSquare,
} from 'lucide-react'
import { SourceList } from '../components/SourceLink'

const STATE_CONFIG = {
  awaiting_review: { color: 'amber', label: 'Awaiting Review' },
  complete: { color: 'green', label: 'Complete' },
  running: { color: 'blue', label: 'Running' },
  analyzing: { color: 'blue', label: 'Analyzing' },
  death_spiral: { color: 'red', label: 'Death Spiral' },
  onboarding: { color: 'slate', label: 'Onboarding' },
  ingesting: { color: 'purple', label: 'Ingesting' },
}

function CriterionCard({ c, type }) {
  const [open, setOpen] = useState(false)
  const borderColor = type === 'inclusion' ? 'border-l-emerald-400' : 'border-l-red-400'
  return (
    <div className={`card border-l-4 ${borderColor} px-4 py-3`}>
      <button
        className="w-full text-left flex items-start gap-2"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="mt-0.5 shrink-0">
          {open ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
        </span>
        <p className="text-sm font-medium text-slate-800 flex-1 leading-snug">
          {c.statement || c.description || c.text || JSON.stringify(c)}
        </p>
      </button>
      {open && (
        <div className="mt-2 ml-5 space-y-1">
          {c.rationale && (
            <p className="text-xs text-slate-500 leading-relaxed">{c.rationale}</p>
          )}
          {(c.source_ids?.length > 0 || c.source_id) && (
            <SourceList ids={c.source_ids?.length ? c.source_ids : [c.source_id]} short />
          )}
        </div>
      )}
    </div>
  )
}

function WorkstreamStep({ icon: Icon, label, status, color }) {
  const statusConfig = {
    done: { text: 'text-emerald-600', bg: 'bg-emerald-50', dot: 'bg-emerald-500' },
    running: { text: 'text-blue-600', bg: 'bg-blue-50', dot: 'bg-blue-500 animate-pulse' },
    pending: { text: 'text-slate-400', bg: 'bg-slate-50', dot: 'bg-slate-300' },
    failed: { text: 'text-red-600', bg: 'bg-red-50', dot: 'bg-red-500' },
  }
  const s = statusConfig[status] || statusConfig.pending
  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg ${s.bg}`}>
      <div className={`w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
      <Icon size={15} className={s.text} />
      <span className={`text-xs font-medium ${s.text}`}>{label}</span>
    </div>
  )
}

export default function ResearchPage() {
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [synthOpen, setSynthOpen] = useState(false)
  const [resolution, setResolution] = useState('')
  const [runResult, setRunResult] = useState(null)

  const { data: project, refetch: refetchProject } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
    refetchInterval: (q) => q.state.data?.state === 'running' || q.state.data?.state === 'analyzing' ? 3000 : false,
  })

  const { data: dbResults } = useQuery({
    queryKey: ['results', projectId],
    queryFn: () => fetchResults(projectId),
    refetchInterval: 30_000,
  })

  const { mutate: run, isPending: isRunning } = useMutation({
    mutationFn: () => runAnalysis(projectId),
    onSuccess: (data) => {
      setRunResult(data)
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['results', projectId] })
    },
  })

  const { mutate: approve, isPending: isApproving } = useMutation({
    mutationFn: () => approveProject(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })

  const { mutate: resolve, isPending: isResolving } = useMutation({
    mutationFn: () => resolveProject(projectId, resolution),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      setResolution('')
    },
  })

  const results = runResult || dbResults
  const criteria = results?.criteria || []
  const synthesis = results?.synthesis || ''
  const verdict = results?.logical_verdict || results?.structural_verdict || results?.latest_verdict

  const state = project?.state || 'unknown'
  const stateConf = STATE_CONFIG[state] || { color: 'slate', label: state }
  const isAnalyzing = state === 'running' || state === 'analyzing' || isRunning

  const inclusion = criteria.filter((c) => (c.criterion_type || c.type) === 'inclusion')
  const exclusion = criteria.filter((c) => (c.criterion_type || c.type) === 'exclusion')

  const workstreamStatus = (ws) => {
    if (!isAnalyzing && results) return 'done'
    if (isAnalyzing) return 'running'
    return 'pending'
  }

  return (
    <div className="h-full flex">
      {/* Left column: pipeline status + controls */}
      <div className="w-72 shrink-0 border-r border-slate-200 bg-white flex flex-col">
        <div className="panel-header">
          <h2 className="text-sm font-semibold text-slate-700">Pipeline</h2>
          <Badge color={stateConf.color}>{stateConf.label}</Badge>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Workstreams */}
          <div>
            <p className="section-title mb-2">Workstreams (parallel)</p>
            <div className="space-y-1.5">
              <WorkstreamStep icon={Layers} label="Parameter Extraction" status={workstreamStatus('param')} />
              <WorkstreamStep icon={BookOpen} label="Literature Synthesis" status={workstreamStatus('synth')} />
              <WorkstreamStep icon={Cpu} label="Cluster Selection" status={workstreamStatus('cluster')} />
            </div>
          </div>

          <div className="border-t border-slate-100 pt-3">
            <p className="section-title mb-2">Validation</p>
            <div className="space-y-1.5">
              <WorkstreamStep
                icon={ShieldCheck}
                label="Structural Check"
                status={results ? 'done' : isAnalyzing ? 'running' : 'pending'}
              />
              <WorkstreamStep
                icon={ShieldCheck}
                label="LLM-as-Judge"
                status={verdict ? 'done' : isAnalyzing ? 'running' : 'pending'}
              />
            </div>
          </div>

          {/* Project info */}
          {project && (
            <div className="border-t border-slate-100 pt-3 text-xs text-slate-500 space-y-1">
              <div className="flex justify-between">
                <span>Iterations</span>
                <span className="font-medium text-slate-700">{project.iteration_count}</span>
              </div>
              <div className="flex justify-between">
                <span>Criteria</span>
                <span className="font-medium text-slate-700">{criteria.length}</span>
              </div>
            </div>
          )}

          {/* Death spiral */}
          {state === 'death_spiral' && (
            <div className="border-t border-slate-100 pt-3">
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <div className="flex items-center gap-1.5 text-red-700 font-medium text-xs mb-1">
                  <AlertTriangle size={14} /> Death Spiral
                </div>
                {project?.death_spiral_reason && (
                  <p className="text-xs text-red-600 mb-2">{project.death_spiral_reason}</p>
                )}
                <textarea
                  className="textarea text-xs mb-2"
                  rows={2}
                  placeholder="Resolution guidance…"
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value)}
                />
                <button
                  className="btn-primary text-xs w-full justify-center"
                  onClick={() => resolve()}
                  disabled={isResolving}
                >
                  {isResolving ? <LoadingSpinner size="sm" /> : 'Resolve & Unlock'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Run button */}
        <div className="p-4 border-t border-slate-200 space-y-2">
          <button
            className="btn-primary w-full justify-center"
            onClick={() => run()}
            disabled={isAnalyzing || state === 'death_spiral'}
          >
            {isAnalyzing ? (
              <><LoadingSpinner size="sm" /> Analyzing…</>
            ) : (
              <><Play size={14} /> Run Analysis</>
            )}
          </button>
          {state === 'awaiting_review' && (
            <button
              className="btn-success w-full justify-center"
              onClick={() => approve()}
              disabled={isApproving}
            >
              {isApproving ? <LoadingSpinner size="sm" /> : <CheckCircle size={14} />}
              Approve Criteria
            </button>
          )}
          {criteria.length > 0 && (
            <button
              className="btn-secondary w-full justify-center text-xs"
              onClick={() => navigate(`/projects/${projectId}/screening`)}
            >
              <CheckSquare size={14} /> Go to Screening
            </button>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto">
        {isAnalyzing && !results && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-500">
            <LoadingSpinner size="lg" />
            <div className="text-center">
              <p className="font-medium">Running parallel workstreams…</p>
              <p className="text-sm mt-1">Parameter extraction · Literature synthesis · Cluster selection</p>
            </div>
          </div>
        )}

        {!isAnalyzing && !results && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-400">
            <Layers size={48} className="opacity-30" />
            <p className="font-medium">No analysis results yet</p>
            <p className="text-sm">Click "Run Analysis" to start the pipeline</p>
          </div>
        )}

        {results && (
          <div className="p-6 space-y-6 max-w-4xl">
            {/* Judge scorecard */}
            {verdict && <JudgeScorecard verdict={verdict} />}

            {/* Synthesis */}
            {synthesis && (
              <div className="card">
                <button
                  className="w-full px-5 py-4 flex items-center justify-between text-left"
                  onClick={() => setSynthOpen((o) => !o)}
                >
                  <div className="flex items-center gap-2">
                    <BookOpen size={16} className="text-slate-500" />
                    <span className="text-sm font-semibold text-slate-800">Literature Synthesis</span>
                  </div>
                  {synthOpen ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                </button>
                {synthOpen && (
                  <div className="px-5 pb-5 border-t border-slate-100">
                    <div className="prose-content pt-4 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                      {synthesis}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Criteria */}
            {criteria.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-base font-semibold text-slate-900">
                    Extracted Criteria <span className="text-slate-400 font-normal">({criteria.length})</span>
                  </h2>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs font-semibold text-emerald-600 uppercase tracking-wide mb-2">
                      Inclusion ({inclusion.length})
                    </p>
                    <div className="space-y-2">
                      {inclusion.map((c, i) => (
                        <CriterionCard key={c.id || i} c={c} type="inclusion" />
                      ))}
                      {inclusion.length === 0 && (
                        <p className="text-xs text-slate-400 italic">None extracted</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-red-500 uppercase tracking-wide mb-2">
                      Exclusion ({exclusion.length})
                    </p>
                    <div className="space-y-2">
                      {exclusion.map((c, i) => (
                        <CriterionCard key={c.id || i} c={c} type="exclusion" />
                      ))}
                      {exclusion.length === 0 && (
                        <p className="text-xs text-slate-400 italic">None extracted</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
