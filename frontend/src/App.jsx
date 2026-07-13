import { Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import NewProjectPage from './pages/NewProjectPage'
import WorkbenchPage from './pages/WorkbenchPage'
import IngestPage from './pages/IngestPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/new" element={<NewProjectPage />} />
      <Route path="/projects/:id" element={<WorkbenchPage />} />
      {/* Detailed pipeline status — reachable, but not the default path */}
      <Route path="/projects/:id/ingest" element={<IngestPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
