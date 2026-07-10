import { ExternalLink } from 'lucide-react'

const PATTERNS = [
  { re: /^pmid:(\d+)$/i,          url: (m) => `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/`,     label: 'PubMed' },
  { re: /^arxiv:(.+)$/i,          url: (m) => `https://arxiv.org/abs/${m[1]}`,                 label: 'arXiv' },
  { re: /^(10\.\d{4,}[\w./:-]+)/, url: (m) => `https://doi.org/${m[1]}`,                       label: 'DOI' },
  { re: /^(NCT\d+)$/i,            url: (m) => `https://clinicaltrials.gov/study/${m[1]}`,       label: 'ClinicalTrials' },
  { re: /^(CARD:\S+)$/i,          url: (m) => `https://card.mcmaster.ca/home`,                  label: 'CARD' },
  { re: /^https?:\/\//,           url: (m) => m[0],                                             label: null },
]

function resolveSource(id) {
  if (!id) return null
  const s = id.trim()
  for (const { re, url, label } of PATTERNS) {
    const m = s.match(re)
    if (m) return { href: url(m), label }
  }
  return null
}

/**
 * Renders a source identifier as a clickable external link when the format is
 * recognised (pmid:, arxiv:, DOI 10.xxx, NCT number, or bare URL).
 * Falls back to a plain <span> for unrecognised formats.
 */
export default function SourceLink({ id, className = '', short = false }) {
  if (!id) return null
  const resolved = resolveSource(id)

  const display = short ? id.slice(0, 24) + (id.length > 24 ? '…' : '') : id

  if (!resolved) {
    return <span className={`font-mono text-xs text-slate-500 ${className}`}>{display}</span>
  }

  return (
    <a
      href={resolved.href}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1 font-mono text-xs text-blue-600 hover:text-blue-800
                  hover:underline underline-offset-2 transition-colors ${className}`}
      title={`Open on ${resolved.label ?? 'web'}: ${id}`}
    >
      {short ? (resolved.label ?? display) : display}
      <ExternalLink size={10} className="shrink-0 opacity-60" />
    </a>
  )
}

/** Render a list of source IDs as inline SourceLink chips. */
export function SourceList({ ids = [], short = false }) {
  if (!ids?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map((id) => (
        <SourceLink key={id} id={id} short={short} />
      ))}
    </div>
  )
}
