import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  fetchClusters, fetchClusterStats, fetchClusterDetail, fetchWorkbenchOptions,
} from '../api'
import ClusterMap from '../components/ClusterMap'
import ConversationPanel from '../components/ConversationPanel'
import SearchableSelect from '../components/SearchableSelect'
import SinglesList from '../components/SinglesList'
import AddSourceBar from '../components/AddSourceBar'
import LoadingSpinner from '../components/LoadingSpinner'
import { Network, Microscope, X, Filter, GitMerge, FileText } from 'lucide-react'

function StatChip({ label, value }) {
  return (
    <div className="px-3 py-1.5 rounded-lg bg-white border border-slate-200">
      <p className="text-[10px] text-slate-400 uppercase tracking-wide leading-none">{label}</p>
      <p className="text-sm font-semibold text-slate-700 mt-0.5">{value}</p>
    </div>
  )
}

export default function WorkbenchPage() {
  const { id: projectId } = useParams()
  const [selected, setSelected] = useState(null)   // selected cluster node
  const [drug, setDrug] = useState('')
  const [disease, setDisease] = useState('')
  const [showAll, setShowAll] = useState(false)    // load all claims in detail
  const [view, setView] = useState('map')          // 'map' | 'singles'
  const [locatedIds, setLocatedIds] = useState([]) // clusters to spotlight on the map

  const { data: clustersData, isLoading: clustersLoading } = useQuery({
    queryKey: ['clusters', projectId],
    queryFn: () => fetchClusters(projectId, true),  // multi-source clusters — the map's story
  })
  const { data: stats } = useQuery({
    queryKey: ['clusterStats', projectId],
    queryFn: () => fetchClusterStats(projectId),
  })
  const { data: detail, isLoading: detailLoading, isFetching: detailFetching } = useQuery({
    queryKey: ['clusterDetail', projectId, selected?.id, showAll],
    queryFn: () => fetchClusterDetail(projectId, selected.id, showAll),
    enabled: !!selected?.id,
    keepPreviousData: true,
  })
  const { data: options } = useQuery({
    queryKey: ['workbenchOptions', projectId],
    queryFn: () => fetchWorkbenchOptions(projectId),
  })

  // Reset "load all" whenever a different cluster is opened.
  useEffect(() => { setShowAll(false) }, [selected?.id])

  const clusters = clustersData?.clusters || []
  const prettyDrug = (k) => k.replace(/\b\w/g, (m) => m.toUpperCase())
  const hasFilter = Boolean(drug || disease)

  // How many clusters match the current filter (for the header hint).
  const matchCount = clusters.filter((c) => {
    if (drug && c.intervention_key !== drug) return false
    if (disease && !(c.diseases || []).includes(disease)) return false
    return true
  }).length

  function clearFilter() { setDrug(''); setDisease('') }

  return (
    <div className="h-full flex flex-col bg-slate-50">
      {/* Header */}
      <div className="px-6 pt-5 pb-3 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
              <Microscope size={17} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-800 leading-none">Research Workbench</h1>
              <p className="text-xs text-slate-400 mt-1">Claim clusters · synthesized evidence · verified sources</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {stats && (
              <>
                <StatChip label="Clusters" value={stats.multi_member_clusters} />
                <StatChip label="Conversations" value={stats.clusters_with_answer} />
                <StatChip label="Supports" value={stats.verdicts?.supports?.count ?? 0} />
                <StatChip label="Contradicts" value={stats.verdicts?.contradicts?.count ?? 0} />
              </>
            )}
          </div>
        </div>

        {/* View tabs: cluster map vs single-paper claims */}
        <div className="mt-3 flex items-center gap-1 border-b border-slate-100 -mb-px">
          {[
            { key: 'map', label: 'Cluster map', icon: GitMerge },
            { key: 'singles', label: 'Single-paper claims', icon: FileText },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                view === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-400 hover:text-slate-600'
              }`}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {/* Add-source-by-DOI bar */}
        {view === 'map' && (
          <div className="mt-3">
            <AddSourceBar projectId={projectId} onLocate={(ids) => { setView('map'); setLocatedIds(ids) }} />
          </div>
        )}

        {/* Drug × disease FILTER bar — highlights matching clusters on the map */}
        {view === 'map' && (
        <div className="mt-3 flex items-end gap-2 flex-wrap">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-slate-400 uppercase tracking-wide">
              Drug / intervention{options?.drugs ? ` (${options.drugs.length})` : ''}
            </label>
            <SearchableSelect
              value={drug}
              onChange={setDrug}
              placeholder="All drugs"
              options={(options?.drugs || []).map((d) => ({ key: d.key, label: prettyDrug(d.key), count: d.count }))}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-slate-400 uppercase tracking-wide">Disease</label>
            <select
              value={disease}
              onChange={(e) => setDisease(e.target.value)}
              className="min-w-[190px] px-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50
                         focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white"
            >
              <option value="">All diseases</option>
              {options?.diseases?.map((d) => (
                <option key={d.key} value={d.key}>{d.label} ({d.count})</option>
              ))}
            </select>
          </div>
          {hasFilter ? (
            <div className="flex items-center gap-2 pb-0.5">
              <span className="text-xs text-slate-500 flex items-center gap-1">
                <Filter size={12} /> {matchCount} cluster{matchCount === 1 ? '' : 's'} highlighted
              </span>
              <button
                onClick={clearFilter}
                className="px-2.5 py-1.5 rounded-lg border border-slate-200 text-slate-500 text-xs
                           hover:bg-slate-50 flex items-center gap-1"
              >
                <X size={12} /> Clear
              </button>
            </div>
          ) : (
            <span className="text-xs text-slate-400 pb-2.5">Pick a drug or disease to highlight related clusters on the map.</span>
          )}
        </div>
        )}
      </div>

      {view === 'singles' ? (
        <div className="flex-1 min-h-0 p-4">
          <SinglesList projectId={projectId} diseases={options?.diseases || []} />
        </div>
      ) : (
      /* Body: map (left) + detail panel (right) */
      <div className="flex-1 min-h-0 flex gap-4 p-4">
        <div className="flex-1 min-w-0 relative">
          {clustersLoading ? (
            <div className="flex items-center justify-center h-full text-slate-400"><LoadingSpinner /></div>
          ) : clusters.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 px-6 border border-dashed border-slate-200 rounded-xl bg-white">
              <Network size={30} className="mb-3 opacity-40" />
              <p className="text-sm font-medium text-slate-500">No claim clusters yet</p>
              <p className="text-xs mt-1 max-w-sm">This project has no multi-source claim clusters. Run the claims pipeline (extract → embed → cluster → synthesize) on its corpus to populate the map.</p>
            </div>
          ) : (
            <ClusterMap
              clusters={clusters}
              selectedId={selected?.id}
              onSelect={setSelected}
              highlightDrug={drug}
              highlightDisease={disease}
              locatedIds={locatedIds}
              onClearLocated={() => setLocatedIds([])}
            />
          )}
        </div>

        {/* Right panel — cluster detail */}
        <div className="w-[440px] shrink-0 bg-white rounded-xl border border-slate-200 flex flex-col overflow-hidden">
          <ConversationPanel
            detail={detail}
            loading={detailLoading && !detail}
            showingAll={showAll}
            onToggleAll={() => setShowAll((v) => !v)}
            loadingMore={detailFetching}
          />
        </div>
      </div>
      )}
    </div>
  )
}
