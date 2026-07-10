import { Cpu, Sparkles, WifiOff, AlertTriangle } from 'lucide-react'
import { EvidenceItem } from './ConversationPanel'
import LoadingSpinner from './LoadingSpinner'

function AnswerCard({ icon: Icon, title, subtitle, answer, error, offline }) {
  return (
    <div className="flex-1 min-w-0 rounded-lg border border-slate-200 bg-white flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-100">
        <Icon size={15} className="text-blue-500" />
        <div>
          <p className="text-sm font-semibold text-slate-700 leading-none">{title}</p>
          <p className="text-[10px] text-slate-400 mt-0.5">{subtitle}</p>
        </div>
      </div>
      <div className="px-4 py-3 text-sm text-slate-700 leading-relaxed">
        {answer ? (
          answer
        ) : offline ? (
          <div className="flex items-start gap-2 text-slate-400">
            <WifiOff size={15} className="shrink-0 mt-0.5" />
            <span>Fine-tuned model offline — start the self-hosted vLLM endpoint (see the LoRA runbook) and set <code className="text-xs bg-slate-100 px-1 rounded">FINETUNED_BASE_URL</code> to compare.</span>
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-amber-600">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            <span className="text-xs break-words">{error}</span>
          </div>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </div>
    </div>
  )
}

/**
 * Live-generation result: base vs fine-tuned answers side by side, plus the
 * retrieved evidence the synthesis drew on. The fine-tuned column degrades to
 * an "offline" note when the GPU endpoint isn't configured/reachable.
 */
export default function ComparisonView({ result, loading }) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
        <LoadingSpinner />
        <p className="text-sm">Retrieving evidence & synthesizing (base + fine-tuned)…</p>
      </div>
    )
  }
  if (!result) return null

  const ftOffline = !result.finetuned_enabled

  return (
    <div className="h-full overflow-y-auto px-5 py-5 space-y-4">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-500 mb-1">Question</p>
        <h3 className="text-[15px] font-semibold text-slate-800 leading-snug">{result.question}</h3>
        <p className="text-[11px] text-slate-400 mt-1">
          Synthesized from <span className="font-medium text-slate-500">{result.members?.length || 0}</span> verified claims
          {result.disease ? <> · {result.disease}</> : null}
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-3">
        <AnswerCard
          icon={Cpu}
          title="Base model"
          subtitle="Llama-3.3-70B (Token Factory)"
          answer={result.base_answer}
          error={result.base_error}
        />
        <AnswerCard
          icon={Sparkles}
          title="Fine-tuned"
          subtitle="LoRA adapter (self-hosted)"
          answer={result.finetuned_answer}
          error={result.finetuned_error}
          offline={ftOffline}
        />
      </div>

      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-2">
          Retrieved evidence
        </p>
        <div className="space-y-2">
          {result.members?.map((m, i) => <EvidenceItem key={i} m={m} />)}
        </div>
      </div>
    </div>
  )
}
