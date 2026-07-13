import { useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Quote, CheckCircle2, AlertCircle, ChevronDown, ChevronUp, Loader2, Sigma, TrendingUp, Calendar, Scale, Bookmark } from 'lucide-react'
import Badge from './Badge'
import SourceLink from './SourceLink'
import CitedAnswer from './CitedAnswer'
import SaveButton from './SaveButton'
import JudgeScorecard from './JudgeScorecard'
import LoadingSpinner from './LoadingSpinner'
import useReadingList from '../hooks/useReadingList'
import { judgeCluster, saveClusterSources } from '../api'

/** LLM-as-judge for the cluster's answer: run once (cached). The scores and
 *  per-dimension rationale are shown as feedback for the researcher's reference. */
function JudgeSection({ detail }) {
  const { id: projectId } = useParams()
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: ['clusterDetail', projectId] })
  const judge = useMutation({ mutationFn: () => judgeCluster(projectId, detail.id), onSuccess: invalidate })

  if (detail.judge) {
    return <JudgeScorecard verdict={detail.judge} />
  }

  return (
    <div>
      <button
        onClick={() => judge.mutate()}
        disabled={judge.isPending}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-slate-200
                   text-sm text-blue-600 hover:bg-blue-50 disabled:opacity-60 transition-colors"
      >
        {judge.isPending
          ? <><Loader2 size={14} className="animate-spin" /> Judging the answer…</>
          : <><Scale size={14} /> Run LLM judge on this answer</>}
      </button>
      {judge.isError && (
        <p className="text-xs text-amber-600 mt-1">{String(judge.error?.message || judge.error)}</p>
      )}
    </div>
  )
}

/** Save every source under this research question to the reading list at once. */
function SaveAllButton({ detail }) {
  const { id: projectId } = useParams()
  const qc = useQueryClient()
  const { savedIds } = useReadingList(projectId)
  const shownSources = [...new Set((detail.members || []).map((m) => m.source_id).filter(Boolean))]
  const allShownSaved = shownSources.length > 0 && shownSources.every((s) => savedIds.has(s))

  const save = useMutation({
    mutationFn: () => saveClusterSources(projectId, detail.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['readingList', projectId] }),
  })

  return (
    <button
      onClick={() => save.mutate()}
      disabled={save.isPending || allShownSaved}
      className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-800 disabled:text-slate-400 disabled:cursor-default"
      title="Save all of this question's sources to the reading list"
    >
      {save.isPending ? <Loader2 size={12} className="animate-spin" /> : <Bookmark size={12} />}
      {allShownSaved ? 'All sources saved' : 'Save all sources'}
    </button>
  )
}

// A field counts as "reported" only if it isn't a null / not-reported marker.
const _NULL_RE = /^\s*(null|none|nr|n\/?a|not applicable|not reported|not explicitly.*|not stated|not specified|unclear)\s*$/i
function isReported(v) {
  return Boolean(v) && !_NULL_RE.test(String(v).trim()) && String(v).trim().length > 0
}
// Significant if a reported p-value < 0.05, or asserted "significant" (not "non-significant").
function isSignificant(v) {
  if (!isReported(v)) return false
  const t = String(v).toLowerCase()
  const m = [...t.matchAll(/p\s*[<=≤]\s*(0?\.\d+|\d+(?:\.\d+)?)/g)]
  if (m.length) return m.some((x) => parseFloat(x[1]) < 0.05)
  return t.includes('significant') && !t.includes('non-significant') && !t.includes('not significant')
}
function truncate(v, n) {
  const s = String(v).trim()
  return s.length > n ? s.slice(0, n) + '…' : s
}
// "2026-07" -> "Jul 2026"; "2025" -> "2025".
const _MON = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function formatPubDate(v) {
  if (!v) return null
  const m = String(v).match(/^(\d{4})(?:-(\d{2}))?$/)
  if (!m) return String(v)
  return m[2] ? `${_MON[parseInt(m[2], 10)] || ''} ${m[1]}`.trim() : m[1]
}

const VERDICT_BADGE = {
  supports: 'green',
  partially_supports: 'amber',
  contradicts: 'red',
  inconclusive: 'slate',
}
const VERDICT_TEXT = {
  supports: 'Supports',
  partially_supports: 'Partially supports',
  contradicts: 'Contradicts',
  inconclusive: 'Inconclusive',
}

function VerdictMix({ mix }) {
  const entries = Object.entries(mix || {}).filter(([, n]) => n > 0)
  if (!entries.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([v, n]) => (
        <Badge key={v} color={VERDICT_BADGE[v]}>{VERDICT_TEXT[v] || v} · {n}</Badge>
      ))}
    </div>
  )
}

/** One piece of evidence: CLAIM + its verdict + the quoted passage + source.
 *  `anchorId` (set for the first card of each source) is the scroll target a
 *  citation number jumps to. */
export function EvidenceItem({ m, anchorId }) {
  return (
    <div id={anchorId} className="rounded-lg border border-slate-200 bg-white px-3.5 py-3 scroll-mt-4 transition-shadow duration-300">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-slate-800 leading-snug flex-1">
          <span className="font-semibold text-slate-500 mr-1">CLAIM:</span>
          {m.claim_text}
        </p>
        <Badge color={VERDICT_BADGE[m.verdict]}>{VERDICT_TEXT[m.verdict] || m.verdict}</Badge>
      </div>
      {m.evidence_quote && (
        <div className="mt-2 flex gap-1.5 text-xs text-slate-500 italic leading-relaxed">
          <Quote size={12} className="shrink-0 mt-0.5 text-slate-300" />
          <span>{m.evidence_quote}</span>
        </div>
      )}
      {/* Objective evidence signals that drive the ranking */}
      {(isReported(m.statistical_significance) || isReported(m.effect_size)) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {isReported(m.statistical_significance) && (
            <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium ${isSignificant(m.statistical_significance) ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`} title="Reported statistical significance">
              <Sigma size={10} /> {truncate(m.statistical_significance, 34)}
            </span>
          )}
          {isReported(m.effect_size) && (
            <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium bg-blue-50 text-blue-600" title="Reported effect size">
              <TrendingUp size={10} /> {truncate(m.effect_size, 40)}
            </span>
          )}
        </div>
      )}
      <div className="mt-2 flex items-center gap-2 flex-wrap">
        <SourceLink id={m.source_id} />
        <SaveButton source_id={m.source_id} added_from="conversation" showLabel />
        {formatPubDate(m.pub_date) && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500" title="Publication date">
            <Calendar size={10} className="text-slate-400" /> {formatPubDate(m.pub_date)}
          </span>
        )}
        {m.doc_type && <span className="text-[10px] uppercase tracking-wide text-slate-400">{m.doc_type}</span>}
        {m.quote_verified ? (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600" title="Quote found verbatim in source">
            <CheckCircle2 size={11} /> quote verified
          </span>
        ) : m.quote_verified === 0 ? (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-600" title="Quote not matched in source text">
            <AlertCircle size={11} /> unverified
          </span>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Renders a cluster's synthesized conversation: the research question, the cited
 * answer, and the per-source evidence that backs it — feature 1's CLAIM /
 * evidence-from-source-X / evidence-from-source-Y layout.
 */
export default function ConversationPanel({ detail, loading, showingAll, onToggleAll, loadingMore }) {
  if (loading) {
    return <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
  }
  if (!detail) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 text-slate-400">
        <Quote size={28} className="mb-3 opacity-40" />
        <p className="text-sm font-medium text-slate-500">Select a cluster</p>
        <p className="text-xs mt-1">Click a node in the map to see its claim, the synthesized evidence, and the sources behind it.</p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-5 space-y-4">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-500 mb-1">Research question</p>
        <h3 className="text-[15px] font-semibold text-slate-800 leading-snug">{detail.question}</h3>
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <VerdictMix mix={detail.verdict_mix} />
          <span className="text-[11px] text-slate-400">
            {detail.member_count} claims · {detail.distinct_document_count} sources
          </span>
        </div>
      </div>

      {detail.answer && (
        <div className="rounded-lg bg-blue-50/60 border border-blue-100 px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-500 mb-1">Synthesized evidence</p>
          <CitedAnswer text={detail.answer} />
        </div>
      )}

      {detail.answer && <JudgeSection detail={detail} />}

      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Evidence — showing {detail.members?.length || 0} of {detail.member_count} verified claims
          </p>
          {detail.id && <SaveAllButton detail={detail} />}
        </div>
        <div className="space-y-2">
          {(() => {
            const seen = new Set()
            return detail.members?.map((m) => {
              const first = m.source_id && !seen.has(m.source_id)
              if (first) seen.add(m.source_id)
              // Anchor only the first card per source → citation jumps land here,
              // and DOM ids stay unique.
              return <EvidenceItem key={m.id} m={m} anchorId={first ? `ev-${m.source_id}` : undefined} />
            })
          })()}
        </div>

        {/* Load-all toggle — only when the cluster has more than the concise set */}
        {(showingAll || (detail.member_count > (detail.shown_count ?? (detail.members?.length || 0)))) && (
          <button
            onClick={onToggleAll}
            disabled={loadingMore}
            className="mt-3 w-full py-2 rounded-lg border border-slate-200 text-sm text-blue-600
                       hover:bg-blue-50 disabled:opacity-60 flex items-center justify-center gap-1.5 transition-colors"
          >
            {loadingMore ? (
              <><Loader2 size={14} className="animate-spin" /> Loading…</>
            ) : showingAll ? (
              <><ChevronUp size={14} /> Show top claims only</>
            ) : (
              <><ChevronDown size={14} /> Load all {detail.member_count} claims</>
            )}
          </button>
        )}
      </div>
    </div>
  )
}
