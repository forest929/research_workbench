import { useId, useMemo } from 'react'
import { isSourceId } from './SourceLink'

// Matches EITHER a bracketed group "[…]" OR a bare source id the model wrote
// without brackets (e.g. "…pmid:12345."). The bracket branch is first so a
// bracketed id is consumed whole and never double-counted by the bare branch.
// A bracket is only treated as a citation if every ;/,-separated token inside is
// a known source id, so incidental brackets ("[95% CI 0.5–0.7]") stay as text.
const CITE_RE = /\[([^[\]]+)\]|(pmid:\d+|nct:NCT\d+|NCT\d+|arxiv:[\w.\/-]+)/gi

/**
 * Parse an LLM-synthesized answer whose inline citations are raw source ids
 * (bracketed "[pmid:12345]" or bare "pmid:12345") into:
 *   - `nodes`: an ordered list of {t:'text'} / {t:'cite'} segments for render
 *   - `references`: ordered unique sources, numbered by first appearance
 * Deterministic and case-insensitive on ids. Pure function — no LLM, no network.
 */
export function parseCitations(text) {
  const order = []
  const indexOf = new Map()
  const idx = (id) => {
    const key = id.toLowerCase()
    if (!indexOf.has(key)) {
      indexOf.set(key, order.length + 1)
      order.push(id)
    }
    return indexOf.get(key)
  }

  const nodes = []
  let last = 0
  for (const m of text.matchAll(CITE_RE)) {
    let indices = null
    if (m[1] !== undefined) {
      // bracketed group — accept only if every token is a source id
      const parts = m[1].split(/[;,]/).map((s) => s.trim()).filter(Boolean)
      if (parts.length && parts.every(isSourceId)) indices = parts.map(idx)
    } else if (m[2] && isSourceId(m[2])) {
      // bare source id written without brackets
      indices = [idx(m[2])]
    }
    if (!indices) continue

    if (m.index > last) nodes.push({ t: 'text', v: text.slice(last, m.index) })
    nodes.push({ t: 'cite', indices })
    last = m.index + m[0].length
  }
  if (last < text.length) nodes.push({ t: 'text', v: text.slice(last) })

  // The model often wraps citations in parentheses, e.g. "…in breast cancer
  // ([pmid:x])." or "…([pmid:x], [pmid:y])". Each bracket becomes a numbered
  // marker, so those parens render as a redundant "([1])" / "([1], [2])". Drop
  // parens that wrap ONLY citations, merging a group into a single "[1, 2]".
  // A parenthetical containing prose (e.g. "(see [1], [2])") is left untouched.
  for (let i = 0; i < nodes.length; i++) {
    const open = nodes[i]
    if (open.t !== 'text' || !open.v.endsWith('(')) continue
    // Walk cite, (separator-text, cite)*, until a text node that opens with ")".
    const cites = []
    let j = i + 1
    let closeNode = null
    while (nodes[j]?.t === 'cite') {
      cites.push(nodes[j])
      const after = nodes[j + 1]
      if (after?.t === 'text' && after.v.startsWith(')')) { closeNode = after; break }
      if (after?.t === 'text' && /^[\s,;]+$/.test(after.v)) { j += 2; continue } // pure separator
      break // prose between citations → not a citation-only group
    }
    if (!closeNode || !cites.length) continue
    const merged = []
    for (const c of cites) for (const ix of c.indices) if (!merged.includes(ix)) merged.push(ix)
    open.v = open.v.slice(0, -1)          // drop "("
    closeNode.v = closeNode.v.slice(1)    // drop ")"
    nodes.splice(i + 1, j - i, { t: 'cite', indices: merged }) // collapse group → one marker
  }

  return { nodes, references: order.map((id, i) => ({ index: i + 1, id })) }
}

/**
 * Renders a cited answer with readable numbered citations ([1], [2, 3]) that
 * link to a References list underneath. Falls back to plain text when the
 * answer carries no recognizable citations.
 */
export default function CitedAnswer({ text, className = '' }) {
  const uid = useId()
  const { nodes, references } = useMemo(() => parseCitations(text || ''), [text])
  const refById = useMemo(() => new Map(references.map((r) => [r.index, r.id])), [references])

  if (!text) return null

  // Clicking a citation jumps to that source's evidence card in the list below
  // (id `ev-<source_id>`, set by ConversationPanel) and briefly highlights it.
  // Falls back to the reference-list entry if the evidence card isn't rendered.
  const flash = (el) => {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-blue-400')
    setTimeout(() => el.classList.remove('ring-2', 'ring-blue-400'), 1400)
  }
  const jumpTo = (index) => {
    const sourceId = refById.get(index)
    // Primary: the source's evidence card in the answer panel.
    const primary =
      (sourceId && document.getElementById(`ev-${sourceId}`)) ||
      document.getElementById(`${uid}-ref-${index}`)
    if (primary) flash(primary)
    // Ask the Papers + Reading panels to reveal this paper (they fetch/scroll to
    // it if it isn't currently on screen — like the claim list does).
    if (sourceId) {
      window.dispatchEvent(new CustomEvent('workbench:reveal-source', { detail: sourceId }))
    }
  }

  return (
    <div className={className}>
      <p className="text-sm text-slate-700 leading-relaxed">
        {nodes.map((n, i) =>
          n.t === 'text' ? (
            <span key={i}>{n.v}</span>
          ) : (
            <button
              key={i}
              type="button"
              onClick={() => jumpTo(n.indices[0])}
              className="mx-0.5 align-baseline text-[11px] font-semibold text-blue-600
                         hover:text-blue-800 hover:underline underline-offset-2"
              title="Jump to this source's evidence"
            >
              [{n.indices.join(', ')}]
            </button>
          )
        )}
      </p>
    </div>
  )
}
