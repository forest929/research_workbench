import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProjectsPage from './pages/ProjectsPage'
import WorkbenchPage from './pages/WorkbenchPage'

export default function App() {
  return (
    <Routes>
      {/* Home: project selection */}
      <Route path="/" element={<Layout />}>
        <Route index element={<ProjectsPage />} />
      </Route>

      {/* Project-scoped: the workbench is the whole app */}
      <Route path="/projects/:id" element={<Layout />}>
        <Route index element={<WorkbenchPage />} />
        <Route path="workbench" element={<WorkbenchPage />} />
        {/* legacy paths fold back into the workbench */}
        <Route path="*" element={<Navigate to="" replace />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
