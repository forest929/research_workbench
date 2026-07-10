import { useState } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  const { id } = useParams()
  const [activeProject, setActiveProject] = useState(id)

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar activeProjectId={activeProject} onProjectChange={setActiveProject} />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
