import { api } from './client'
export { api }

// Projects
export const fetchProjects = () => api.get('/projects')
export const fetchProject = (id) => api.get(`/projects/${id}`)
export const createProject = (body) => api.post('/projects', body)
export const deleteProject = (id) => api.delete(`/projects/${id}`)
export const approveProject = (id) => api.post(`/projects/${id}/approve`)
export const resolveProject = (id, resolution_guidance) =>
  api.post(`/projects/${id}/resolve`, { resolution_guidance })

// Search-driven ingest
export const triggerSearch = (projectId, body) =>
  api.post(`/projects/${projectId}/search`, body)
export const fetchIngestStatus = (projectId) =>
  api.get(`/projects/${projectId}/ingest-status`)
export const triggerAnalyze = (projectId) =>
  api.post(`/projects/${projectId}/analyze`)
export const cancelBuild = (projectId) =>
  api.post(`/projects/${projectId}/cancel`)
export const fetchAnalyzeStatus = (projectId) =>
  api.get(`/projects/${projectId}/analyze-status`)
export const ingestDois = (projectId, dois) =>
  api.post(`/projects/${projectId}/ingest-dois`, { dois })
// Multi-file (CSV/Excel/PDF, or a whole folder) — multipart, so raw fetch.
export const ingestFiles = (projectId, fileList) => {
  const fd = new FormData()
  for (const f of fileList) fd.append('files', f)
  return fetch(`/api/projects/${projectId}/ingest-files`, { method: 'POST', body: fd })
    .then(async (r) => { if (!r.ok) throw new Error(await r.text()); return r.json() })
}

// Workbench — claim clusters, conversations, live generation
export const fetchClusters = (projectId, multiOnly = true) =>
  api.get(`/projects/${projectId}/clusters?multi_only=${multiOnly}`)
export const fetchClusterDetail = (projectId, clusterId, full = false) =>
  api.get(`/projects/${projectId}/clusters/${clusterId}${full ? '?full=true' : ''}`)
export const fetchClusterStats = (projectId) =>
  api.get(`/projects/${projectId}/clusters/stats`)
export const judgeCluster = (projectId, clusterId) =>
  api.post(`/projects/${projectId}/clusters/${clusterId}/judge`)
export const saveClusterSources = (projectId, clusterId) =>
  api.post(`/projects/${projectId}/clusters/${clusterId}/save-sources`)
export const fetchWorkbenchOptions = (projectId) =>
  api.get(`/projects/${projectId}/workbench/options`)
export const fetchPapers = (projectId, { q = '', limit = 50, offset = 0 } = {}) => {
  const p = new URLSearchParams()
  if (q) p.set('q', q)
  p.set('limit', limit); p.set('offset', offset)
  return api.get(`/projects/${projectId}/workbench/papers?${p.toString()}`)
}
export const saveFilteredPapers = (projectId, body) =>
  api.post(`/projects/${projectId}/workbench/save-filtered`, body)
export const fetchPaper = (projectId, sourceId) =>
  api.get(`/projects/${projectId}/workbench/papers?source_id=${encodeURIComponent(sourceId)}&limit=1`)
export const askAssistant = (projectId, question) =>
  api.post(`/projects/${projectId}/workbench/assistant`, { question })
export const fetchAssistantHistory = (projectId) =>
  api.get(`/projects/${projectId}/workbench/assistant/history`)
export const deleteAssistantAnswer = (projectId, id) =>
  api.delete(`/projects/${projectId}/workbench/assistant/history/${id}`)
export const spinoffFromReadingList = (projectId, name) =>
  api.post(`/projects/${projectId}/reading-list/spinoff`, { name })
export const updateDiseaseVocab = (projectId, vocab) =>
  api.put(`/projects/${projectId}/workbench/disease-vocab`, { vocab })
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

// Reading list — a project's curated set of bookmarked publications
export const fetchReadingList = (projectId) =>
  api.get(`/projects/${projectId}/reading-list`)
export const savePublication = (projectId, body) =>
  api.post(`/projects/${projectId}/reading-list`, body)
export const deletePublication = (projectId, sourceId) =>
  // source_id sits in a :path segment — encode each part but keep the slashes,
  // so ids like "doi:10.1001/jama.2020.1" route intact.
  api.delete(`/projects/${projectId}/reading-list/${sourceId.split('/').map(encodeURIComponent).join('/')}`)
