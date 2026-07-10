import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Search, Check } from 'lucide-react'

/**
 * Lightweight searchable dropdown (no external dependency). Used for the drug
 * filter, which can have hundreds of options — a plain <select> sorted by count
 * isn't typeable. Options: [{ key, label, count }]. `value` is the selected key
 * ('' = the "all" sentinel).
 */
export default function SearchableSelect({ value, onChange, options, placeholder = 'All', minWidth = 240 }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setQuery('') } }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const selected = options.find((o) => o.key === value)
  const q = query.trim().toLowerCase()
  const matched = q
    ? options.filter((o) => (o.label || o.key).toLowerCase().includes(q))
    : options
  // Cap rendered rows — the drug list can be thousands; render only the top slice
  // (options arrive pre-sorted by count) so the menu stays fast. Search narrows it.
  const RENDER_CAP = 60
  const filtered = matched.slice(0, RENDER_CAP)
  const truncated = matched.length - filtered.length

  function pick(k) { onChange(k); setOpen(false); setQuery('') }

  return (
    <div ref={ref} className="relative" style={{ minWidth }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm rounded-lg
                   border border-slate-200 bg-slate-50 hover:bg-white
                   focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        <span className={selected ? 'text-slate-800 truncate' : 'text-slate-400'}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown size={14} className="shrink-0 text-slate-400" />
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg overflow-hidden">
          <div className="flex items-center gap-1.5 px-2.5 py-2 border-b border-slate-100">
            <Search size={13} className="text-slate-400 shrink-0" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-full text-sm outline-none bg-transparent placeholder:text-slate-300"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto py-1">
            <li
              onClick={() => pick('')}
              className={`px-3 py-1.5 text-sm cursor-pointer flex items-center justify-between hover:bg-slate-50 ${!value ? 'text-blue-600 font-medium' : 'text-slate-600'}`}
            >
              {placeholder}
              {!value && <Check size={13} />}
            </li>
            {filtered.map((o) => (
              <li
                key={o.key}
                onClick={() => pick(o.key)}
                className={`px-3 py-1.5 text-sm cursor-pointer flex items-center justify-between gap-2 hover:bg-slate-50 ${o.key === value ? 'text-blue-600 font-medium' : 'text-slate-700'}`}
              >
                <span className="truncate">{o.label}</span>
                <span className="shrink-0 text-[11px] text-slate-400">
                  {o.count}{o.key === value && <Check size={13} className="inline ml-1 -mt-0.5 text-blue-600" />}
                </span>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-xs text-slate-400">No matches</li>
            )}
            {truncated > 0 && (
              <li className="px-3 py-1.5 text-[11px] text-slate-400 italic">
                +{truncated} more — type to search
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
