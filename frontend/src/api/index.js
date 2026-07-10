import { api } from './client'
export { api }

// Projects
export const fetchProjects = () => api.get('/projects')
export const fetchProject = (id) => api.get(`/projects/${id}`)
export const createProject = (body) => api.post('/projects', body)
export const approveProject = (id) => api.post(`/projects/${id}/approve`)
export const resolveProject = (id, resolution_guidance) =>
  api.post(`/projects/${id}/resolve`, { resolution_guidance })

// Documents
export const fetchDocuments = (projectId) => api.get(`/projects/${projectId}/documents`)
export const ingestDocument = (projectId, body) => api.post(`/projects/${projectId}/documents`, body)

// Research
export const runAnalysis = (projectId) => api.post(`/projects/${projectId}/run`)
export const fetchResults = (projectId) => api.get(`/projects/${projectId}/results`)

// Criteria
export const fetchCriteria = (projectId) => api.get(`/projects/${projectId}/criteria`)
export const updateCriterion = (projectId, criterionId, body) =>
  api.patch(`/projects/${projectId}/criteria/${criterionId}`, body)
export const deleteCriterion = (projectId, criterionId) =>
  api.delete(`/projects/${projectId}/criteria/${criterionId}`)

// Screening
export const fetchScreeningQueue = (projectId, limit = 30) =>
  api.get(`/projects/${projectId}/screening/queue?limit=${limit}`)
export const llmPredict = (projectId, docId) =>
  api.post(`/projects/${projectId}/screening/${docId}/llm-predict`)
export const recordDecision = (projectId, docId, body) =>
  api.post(`/projects/${projectId}/screening/${docId}/decide`, body)
export const fetchScreeningStats = (projectId) =>
  api.get(`/projects/${projectId}/screening/stats`)
export const fetchPreferences = (projectId) =>
  api.get(`/projects/${projectId}/screening/preferences`)

// Search-driven ingest
export const triggerSearch = (projectId, body) =>
  api.post(`/projects/${projectId}/search`, body)
export const fetchIngestStatus = (projectId) =>
  api.get(`/projects/${projectId}/ingest-status`)

// Export — CSV/Excel are direct download URLs; Google Sheets is a POST
export const exportCsvUrl   = (projectId) => `/api/projects/${projectId}/export/csv`
export const exportExcelUrl = (projectId) => `/api/projects/${projectId}/export/excel`
export const exportGoogleSheets = (projectId, body) =>
  api.post(`/projects/${projectId}/export/google-sheets`, body)

// Discrepancy
export const fetchDiscrepancy = (projectId) =>
  api.get(`/projects/${projectId}/discrepancy`)

// Report
export const fetchReport = (projectId) =>
  api.get(`/projects/${projectId}/report`)

// Artifacts
export const fetchArtifact = (projectId) =>
  api.get(`/projects/${projectId}/artifact`)

// Workbench — claim clusters, conversations, live generation
export const fetchClusters = (projectId, multiOnly = true) =>
  api.get(`/projects/${projectId}/clusters?multi_only=${multiOnly}`)
export const fetchClusterDetail = (projectId, clusterId, full = false) =>
  api.get(`/projects/${projectId}/clusters/${clusterId}${full ? '?full=true' : ''}`)
export const fetchClusterStats = (projectId) =>
  api.get(`/projects/${projectId}/clusters/stats`)
export const fetchWorkbenchOptions = (projectId) =>
  api.get(`/projects/${projectId}/workbench/options`)
export const fetchSingleClaims = (projectId, { q = '', disease = '', verdict = '', limit = 30, offset = 0 } = {}) => {
  const p = new URLSearchParams()
  if (q) p.set('q', q)
  if (disease) p.set('disease', disease)
  if (verdict) p.set('verdict', verdict)
  p.set('limit', limit); p.set('offset', offset)
  return api.get(`/projects/${projectId}/workbench/single-claims?${p.toString()}`)
}
export const generateConversation = (projectId, body) =>
  api.post(`/projects/${projectId}/workbench/generate`, body)
export const addSource = (projectId, doi) =>
  api.post(`/projects/${projectId}/workbench/add-source`, { doi })
export const fetchUserSources = (projectId) =>
  api.get(`/projects/${projectId}/workbench/user-sources`)
