import { NavLink, Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchProjects } from '../api'
import { BookOpen, BookMarked, Microscope, Database, Plus, LayoutGrid } from 'lucide-react'

const NAV = [
  { to: 'ingest', label: 'Import & analyze', icon: Database },
  { to: 'papers', label: 'Papers', icon: BookOpen },
  { to: '', label: 'Workbench', icon: Microscope },
  { to: 'reading-list', label: 'Reading list', icon: BookMarked },
]

const STATE_COLOR = {
  awaiting_review: 'bg-amber-400',
  complete: 'bg-emerald-400',
  running: 'bg-blue-400',
  analyzing: 'bg-blue-400',
  death_spiral: 'bg-red-400',
  onboarding: 'bg-slate-300',
  ingesting: 'bg-violet-400',
}

const linkClass = ({ isActive }) =>
  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
    isActive ? 'bg-blue-50 text-blue-700 font-medium' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
  }`

export default function Sidebar({ activeProjectId }) {
  const { id: routeId } = useParams()
  const navigate = useNavigate()
  const projectId = activeProjectId || routeId

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
    refetchInterval: 30_000,
  })
  const project = projects.find((p) => p.id === projectId)

  return (
    <aside className="w-60 shrink-0 bg-white border-r border-slate-200 flex flex-col h-screen">
      {/* Wordmark */}
      <div className="px-4 h-16 flex items-center border-b border-slate-100">
        <Link to="/" className="flex items-center gap-2.5 group">
          <span className="h-7 w-7 rounded-md bg-slate-900 text-white grid place-items-center font-display text-sm leading-none">
            R
          </span>
          <span className="font-display text-[15px] text-slate-900 leading-[1.1] group-hover:text-blue-700 transition-colors">
            Research<br />Workbench
          </span>
        </Link>
      </div>

      {/* Top actions */}
      <div className="px-3 pt-4 pb-2 space-y-0.5">
        <NavLink to="/" end className={linkClass}>
          <LayoutGrid size={16} /> Projects
        </NavLink>
        <button
          onClick={() => navigate('/new')}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium
                     bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          <Plus size={16} /> New review
        </button>
      </div>

      {/* Active project + its sections */}
      {projectId && (
        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
          <div className="px-3 pt-2 pb-3">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400 mb-1.5">Current review</p>
            <p className="text-sm font-medium text-slate-800 leading-snug line-clamp-2">
              {project?.name || 'Loading…'}
            </p>
            {project && (
              <span className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-slate-500">
                <span className={`w-1.5 h-1.5 rounded-full ${STATE_COLOR[project.state] || 'bg-slate-300'}`} />
                {project.state?.replace(/_/g, ' ')}
              </span>
            )}
          </div>
          <nav className="space-y-0.5">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={`/projects/${projectId}${to ? `/${to}` : ''}`} end={to === ''} className={linkClass}>
                <Icon size={16} /> {label}
              </NavLink>
            ))}
          </nav>
        </div>
      )}

      {!projectId && (
        <div className="flex-1 px-4 py-6 text-sm text-slate-400 leading-relaxed">
          Pick a review to open its workbench, or start a new one.
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-3 border-t border-slate-100">
        <p className="text-[11px] text-slate-400">Nebius AI Cloud</p>
      </div>
    </aside>
  )
}
