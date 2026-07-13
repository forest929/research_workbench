import { useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchReadingList, savePublication, deletePublication } from '../api'

/**
 * Reading-list state + mutations for a project. Backs both the save/unsave
 * toggle (SaveButton) and the Reading list page. The `savedIds` Set makes
 * `isSaved(source_id)` an O(1) lookup for the toggle.
 */
export default function useReadingList(projectId) {
  const qc = useQueryClient()
  const key = ['readingList', projectId]

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => fetchReadingList(projectId),
    enabled: !!projectId,
  })

  const items = data?.items || []
  const savedIds = useMemo(() => new Set(items.map((i) => i.source_id)), [items])

  const invalidate = () => qc.invalidateQueries({ queryKey: key })

  const save = useMutation({
    mutationFn: (body) => savePublication(projectId, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (sourceId) => deletePublication(projectId, sourceId),
    onSuccess: invalidate,
  })

  return {
    items,
    isLoading,
    savedIds,
    isSaved: (sourceId) => savedIds.has(sourceId),
    save,
    remove,
    toggle: (pub) => {
      if (savedIds.has(pub.source_id)) remove.mutate(pub.source_id)
      else save.mutate(pub)
    },
  }
}
