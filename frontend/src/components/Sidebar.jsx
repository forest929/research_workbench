import { NavLink, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchProjects } from '../api'
import {
  LayoutDashboard, FileText, FlaskConical, CheckSquare,
  GitCompare, BarChart3, BookOpen, ChevronDown, Beaker, Search, Microscope,
} from 'lucide-react'

const NAV = [
  { to: '', label: 'Workbench', icon: Microscope },
]

const STATE_COLOR = {
  awaiting_review: 'bg-amber-400',
  complete: 'bg-emerald-400',
  running: 'bg-blue-400',
  analyzing: 'bg-blue-400',
  death_spiral: 'bg-red-400',
  onboarding: 'bg-slate-400',
  ingesting: 'bg-purple-400',
}

export default function Sidebar({ activeProjectId, onProjectChange }) {
  const { id: routeId } = useParams()
  const navigate = useNavigate()

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
    refetchInterval: 30_000,
  })

  const projectId = activeProjectId || routeId

  function handleSelect(e) {
    const pid = e.target.value
    if (pid === '__new') {
      navigate('/')
      return
    }
    onProjectChange?.(pid)
    navigate(`/projects/${pid}`)
  }

  return (
    <aside className="w-56 shrink-0 bg-navy-900 flex flex-col h-screen">
      {/* Brand */}
      <div className="px-4 py-5 border-b border-white/10">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center shrink-0">
            <Beaker size={16} className="text-white" />
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-none">Portfolio</p>
            <p className="text-blue-300 text-xs mt-0.5">Architect AI</p>
          </div>
        </div>
      </div>

      {/* Project selector */}
      <div className="px-3 py-3 border-b border-white/10">
        <p className="text-xs font-medium text-slate-400 mb-1.5 px-1">Active Project</p>
        <div className="relative">
          <select
            value={projectId || ''}
            onChange={handleSelect}
            className="w-full bg-white/10 text-white text-xs py-2 pl-3 pr-7 rounded-lg
                       border border-white/20 appearance-none cursor-pointer
                       focus:outline-none focus:ring-2 focus:ring-blue-400
                       hover:bg-white/15 transition-colors"
          >
            {!projectId && <option value="">— select project —</option>}
            {projects.map((p) => (
              <option key={p.id} value={p.id} className="bg-slate-800 text-white">
                {p.name.length > 22 ? p.name.slice(0, 22) + '…' : p.name}
              </option>
            ))}
            <option value="__new" className="bg-slate-800 text-blue-300">+ New project</option>
          </select>
          <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-300 pointer-events-none" />
        </div>

        {projectId && projects.length > 0 && (() => {
          const p = projects.find((x) => x.id === projectId)
          const dot = STATE_COLOR[p?.state] || 'bg-slate-400'
          return p ? (
            <div className="flex items-center gap-1.5 mt-2 px-1">
              <div className={`w-1.5 h-1.5 rounded-full ${dot}`} />
              <span className="text-xs text-slate-400">{p.state?.replace(/_/g, ' ')}</span>
            </div>
          ) : null
        })()}
      </div>

      {/* Nav */}
      {projectId && (
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon }) => {
            const href = `/projects/${projectId}${to ? `/${to}` : ''}`
            return (
              <NavLink
                key={to}
                to={href}
                end={to === ''}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white font-medium'
                      : 'text-slate-300 hover:bg-white/10 hover:text-white'
                  }`
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            )
          })}
        </nav>
      )}

      {!projectId && (
        <div className="flex-1 px-4 py-6">
          <button
            onClick={() => navigate('/')}
            className="w-full py-2.5 rounded-lg border border-dashed border-white/20 text-slate-400
                       text-sm hover:bg-white/5 transition-colors flex items-center justify-center gap-2"
          >
            <LayoutDashboard size={14} />
            Create project
          </button>
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-3 border-t border-white/10">
        <p className="text-xs text-slate-500">Nebius AI Cloud · v0.1</p>
      </div>
    </aside>
  )
}
