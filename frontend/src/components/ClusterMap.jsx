import { useMemo, useRef, useState, useCallback, useEffect } from 'react'
import { ZoomIn, ZoomOut, Maximize2, Crosshair, X } from 'lucide-react'

// Verdict → fill. Shared vocabulary with the rest of the workbench.
export const VERDICT_COLOR = {
  supports: '#10b981',           // emerald
  partially_supports: '#f59e0b', // amber
  contradicts: '#ef4444',        // red
  inconclusive: '#94a3b8',       // slate
}
export const VERDICT_LABEL = {
  supports: 'Supports',
  partially_supports: 'Partial',
  contradicts: 'Contradicts',
  inconclusive: 'Inconclusive',
}

const VIEW_W = 1000
const VIEW_H = 700
const PAD = 60
const DIM_FILL = '#cbd5e1'
const USER_STROKE = '#7c3aed' // violet — user-added clusters (feature flag; harmless if unused)

// Singletons (single-paper claims) render as tiny dots; multi-source clusters
// scale with claim count (sqrt so area ≈ count), lightly capped.
function radiusFor(memberCount) {
  const n = memberCount || 1
  if (n <= 1) return 2.6
  return Math.min(52, 5 + Math.sqrt(n) * 2.6)
}

// Relaxation only runs over the big (multi-source) bubbles — O(n²) is fine for a
// few hundred but not for ~16k. Singletons keep their raw PCA positions (they're
// tiny, so overlap is harmless). minDist = |rA-rB|+margin forbids full occlusion,
// so no big bubble is ever completely hidden.
function relaxBig(big, iterations = 60) {
  for (let it = 0; it < iterations; it++) {
    let moved = false
    for (let i = 0; i < big.length; i++) {
      for (let j = i + 1; j < big.length; j++) {
        const a = big[i], b = big[j]
        let dx = b.px - a.px, dy = b.py - a.py
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01
        const minDist = Math.abs(a.r - b.r) + 9
        if (dist < minDist) {
          const push = (minDist - dist) / 2
          const ux = dx / dist, uy = dy / dist
          a.px -= ux * push; a.py -= uy * push
          b.px += ux * push; b.py += uy * push
          moved = true
        }
      }
    }
    if (!moved) break
  }
}

function layout(clusters) {
  if (!clusters.length) return []
  const xs = clusters.map((c) => c.x)
  const ys = clusters.map((c) => c.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  const nodes = clusters.map((c) => ({
    ...c,
    px: PAD + ((c.x - minX) / spanX) * (VIEW_W - 2 * PAD),
    py: PAD + ((c.y - minY) / spanY) * (VIEW_H - 2 * PAD),
    r: radiusFor(c.member_count),
  }))
  relaxBig(nodes.filter((n) => (n.member_count || 0) > 1))
  return nodes
}

export default function ClusterMap({ clusters, selectedId, onSelect, highlightDrug, highlightDisease, locatedIds = [], onClearLocated }) {
  const nodes = useMemo(() => layout(clusters), [clusters])
  // Big bubbles first so tiny singletons land on top and stay hoverable.
  const drawOrder = useMemo(() => [...nodes].sort((a, b) => b.r - a.r), [nodes])

  const svgRef = useRef(null)
  const [view, setView] = useState({ x: 0, y: 0, w: VIEW_W, h: VIEW_H })
  const [hovered, setHovered] = useState(null)
  const drag = useRef(null)

  // Clusters to spotlight (e.g. "locate this DOI's source on the map").
  const locatedSet = useMemo(() => new Set(locatedIds), [locatedIds])
  const locatedNodes = useMemo(() => nodes.filter((n) => locatedSet.has(n.id)), [nodes, locatedSet])

  // Pan/zoom to fit the located clusters whenever the located set changes.
  useEffect(() => {
    if (!locatedNodes.length) return
    const minX = Math.min(...locatedNodes.map((p) => p.px - p.r))
    const maxX = Math.max(...locatedNodes.map((p) => p.px + p.r))
    const minY = Math.min(...locatedNodes.map((p) => p.py - p.r))
    const maxY = Math.max(...locatedNodes.map((p) => p.py + p.r))
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
    const scale = Math.max((maxX - minX) / (VIEW_W * 0.5), (maxY - minY) / (VIEW_H * 0.5), 0.18)
    const w = VIEW_W * scale, h = VIEW_H * scale
    setView({ x: cx - w / 2, y: cy - h / 2, w, h })
  }, [locatedNodes])

  const reset = useCallback(() => setView({ x: 0, y: 0, w: VIEW_W, h: VIEW_H }), [])
  const k = view.w / VIEW_W

  const hasSelection = Boolean(highlightDrug || highlightDisease)
  const matches = useCallback((n) => {
    if (highlightDrug && n.intervention_key !== highlightDrug) return false
    if (highlightDisease && !(n.diseases || []).includes(highlightDisease)) return false
    return true
  }, [highlightDrug, highlightDisease])

  function toSvg(evt) {
    const rect = svgRef.current.getBoundingClientRect()
    return {
      x: view.x + ((evt.clientX - rect.left) / rect.width) * view.w,
      y: view.y + ((evt.clientY - rect.top) / rect.height) * view.h,
    }
  }
  function onWheel(evt) {
    evt.preventDefault()
    const factor = evt.deltaY > 0 ? 1.12 : 1 / 1.12
    const p = toSvg(evt)
    const w = Math.min(VIEW_W * 1.6, Math.max(VIEW_W * 0.04, view.w * factor))
    const h = w * (VIEW_H / VIEW_W)
    setView({ x: p.x - ((p.x - view.x) * w) / view.w, y: p.y - ((p.y - view.y) * h) / view.h, w, h })
  }
  function onMouseDown(evt) {
    drag.current = { startX: evt.clientX, startY: evt.clientY, view: { ...view }, moved: false }
  }
  function onMouseMove(evt) {
    if (!drag.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const dx = ((evt.clientX - drag.current.startX) / rect.width) * drag.current.view.w
    const dy = ((evt.clientY - drag.current.startY) / rect.height) * drag.current.view.h
    if (Math.abs(evt.clientX - drag.current.startX) > 3 || Math.abs(evt.clientY - drag.current.startY) > 3) {
      drag.current.moved = true
    }
    setView({ ...drag.current.view, x: drag.current.view.x - dx, y: drag.current.view.y - dy })
  }
  function endDrag() { drag.current = null }
  function handleNodeClick(node) { if (!drag.current?.moved) onSelect?.(node) }
  const zoomBtn = (delta) => () => {
    const w = Math.min(VIEW_W * 1.6, Math.max(VIEW_W * 0.04, view.w * delta))
    const h = w * (VIEW_H / VIEW_W)
    const cx = view.x + view.w / 2, cy = view.y + view.h / 2
    setView({ x: cx - w / 2, y: cy - h / 2, w, h })
  }

  // Base circle. Uses non-scaling stroke so it needs no zoom factor, and reads
  // no hover state — so the memoized base layer never re-renders on hover/zoom.
  function baseCircle(n) {
    const isSel = n.id === selectedId
    const dim = hasSelection && !matches(n)
    const isMatch = hasSelection && matches(n)
    const isUser = n.origin === 'user'
    const fill = dim ? DIM_FILL : (VERDICT_COLOR[n.dominant_verdict] || VERDICT_COLOR.inconclusive)
    let opacity = 0.62
    if (dim) opacity = 0.1
    else if (isSel || isMatch || isUser) opacity = 0.92
    const stroke = isSel ? '#2563eb' : isUser ? USER_STROKE : (isMatch ? '#1d4ed8' : '#fff')
    const sw = isSel ? 2.6 : isUser ? 2.2 : (isMatch ? 1.8 : 0.7)
    return (
      <circle
        key={n.id}
        cx={n.px} cy={n.py} r={n.r}
        fill={fill} fillOpacity={opacity}
        stroke={stroke} strokeWidth={sw}
        strokeDasharray={isUser ? '3 2' : undefined}
        vectorEffect="non-scaling-stroke"
        style={{ cursor: dim ? 'default' : 'pointer' }}
        onMouseEnter={() => setHovered(n)}
        onClick={() => !dim && handleNodeClick(n)}
      />
    )
  }

  // Memoized static layer: recomputes only when the node set or selection/filter
  // changes — NOT on hover, pan, or zoom. Critical for ~16k circles.
  const baseLayer = useMemo(
    () => drawOrder.map(baseCircle),
    [drawOrder, selectedId, hasSelection, highlightDrug, highlightDisease]  // eslint-disable-line
  )

  // Labels for the filtered matches (when few) — hover/selected get their own.
  const matchLabels = useMemo(() => {
    if (!hasSelection) return []
    const matched = nodes.filter(matches)
    if (matched.length > 14) return []
    return matched
  }, [nodes, hasSelection, matches])

  function nodeLabel(n, { emphasised = false } = {}) {
    return (
      <text
        x={n.px} y={n.py - n.r - 5 * k}
        textAnchor="middle" fontSize={(emphasised ? 13 : 10.5) * k}
        fontWeight={emphasised ? 700 : 600}
        fill={emphasised ? '#1d4ed8' : '#334155'}
        stroke="#fff" strokeWidth={(emphasised ? 3 : 2.5) * k} paintOrder="stroke"
        pointerEvents="none"
      >
        {n.intervention_key}{emphasised ? ` · ${n.member_count}` : ''}
      </text>
    )
  }

  return (
    <div className="relative w-full h-full bg-slate-50 rounded-xl overflow-hidden border border-slate-200">
      <div className="absolute top-3 right-3 z-10 flex flex-col gap-1.5">
        <button onClick={zoomBtn(1 / 1.3)} className="p-1.5 bg-white rounded-md shadow-sm border border-slate-200 text-slate-600 hover:bg-slate-50" title="Zoom in"><ZoomIn size={15} /></button>
        <button onClick={zoomBtn(1.3)} className="p-1.5 bg-white rounded-md shadow-sm border border-slate-200 text-slate-600 hover:bg-slate-50" title="Zoom out"><ZoomOut size={15} /></button>
        <button onClick={reset} className="p-1.5 bg-white rounded-md shadow-sm border border-slate-200 text-slate-600 hover:bg-slate-50" title="Reset view"><Maximize2 size={15} /></button>
      </div>

      {hasSelection && !locatedNodes.length && (
        <div className="absolute top-3 left-3 z-10 bg-blue-600 text-white rounded-lg shadow-sm px-3 py-1.5 text-xs font-medium">
          Highlighting {highlightDrug ? <span className="font-semibold">{highlightDrug}</span> : 'all drugs'}
          {highlightDisease ? <> · {highlightDisease}</> : null}
        </div>
      )}

      {locatedNodes.length > 0 && (
        <div className="absolute top-3 left-3 z-10 bg-amber-500 text-white rounded-lg shadow-sm px-3 py-1.5 text-xs font-medium flex items-center gap-2">
          <Crosshair size={13} />
          Located in {locatedNodes.length} cluster{locatedNodes.length === 1 ? '' : 's'}
          <button onClick={() => onClearLocated?.()} className="ml-1 hover:bg-white/20 rounded p-0.5"><X size={12} /></button>
        </div>
      )}

      <div className="absolute bottom-3 left-3 z-10 bg-white/90 backdrop-blur rounded-lg shadow-sm border border-slate-200 px-3 py-2">
        <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Dominant verdict</p>
        <div className="flex flex-col gap-1">
          {Object.entries(VERDICT_LABEL).map(([k2, label]) => (
            <div key={k2} className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: VERDICT_COLOR[k2] }} />
              <span className="text-[11px] text-slate-600">{label}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-1.5 mt-1.5 pt-1.5 border-t border-slate-100">
          <span className="w-2.5 h-2.5 rounded-full border-2 border-dashed" style={{ borderColor: USER_STROKE }} />
          <span className="text-[11px] text-slate-600">Your added source</span>
        </div>
        <p className="text-[10px] text-slate-400 mt-1.5">Node size ∝ claims · drag to pan · scroll to zoom</p>
      </div>

      <svg
        ref={svgRef}
        className="w-full h-full cursor-grab active:cursor-grabbing"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={() => { endDrag(); setHovered(null) }}
      >
        {baseLayer}

        {matchLabels
          .filter((n) => n.id !== hovered?.id)
          .map((n) => <g key={`lbl-${n.id}`}>{nodeLabel(n, { emphasised: true })}</g>)}

        {/* Located clusters: pulsing amber spotlight rings + labels, drawn on top. */}
        {locatedNodes.map((n) => (
          <g key={`loc-${n.id}`} pointerEvents="none">
            <circle
              cx={n.px} cy={n.py} r={n.r + 7} fill="none"
              stroke="#f59e0b" strokeWidth={3} vectorEffect="non-scaling-stroke"
              className="animate-pulse"
            />
            <text
              x={n.px} y={n.py - n.r - 10} textAnchor="middle"
              fontSize={12 * k} fontWeight={700} fill="#b45309"
              stroke="#fff" strokeWidth={3 * k} paintOrder="stroke"
            >
              {n.intervention_key}
            </text>
          </g>
        ))}

        {/* Hovered node re-drawn on top (never occluded) + its label. Only this
            re-renders on hover — the base layer above stays put. */}
        {hovered && (
          <g pointerEvents="none">
            <circle
              cx={hovered.px} cy={hovered.py} r={hovered.r}
              fill={VERDICT_COLOR[hovered.dominant_verdict] || VERDICT_COLOR.inconclusive}
              fillOpacity={0.95} stroke="#1d4ed8" strokeWidth={2} vectorEffect="non-scaling-stroke"
            />
            {nodeLabel(hovered, { emphasised: true })}
          </g>
        )}
      </svg>
    </div>
  )
}
