import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sandboxCastArchivesKey, sandboxRelatedCastArchivesKey, sandboxMemoryArchiveKey, storySandboxBranchesKey } from '@/shared/queries/keys'
import { fetchSandboxCastArchives, fetchSandboxRelatedCastArchives, fetchSandboxMemoryArchive } from '@/shared/utils/archives'

export type SandboxBranch = {
  id: string
  chapter: number
  name: string
  createdAt: string
  updatedAt: string
}

function parseBranch(raw: {
  id?: string; chapter?: number; name?: string; created_at?: string; updated_at?: string
}): SandboxBranch {
  return {
    id: raw.id ?? '', chapter: raw.chapter ?? 0, name: raw.name ?? '',
    createdAt: raw.created_at ?? '', updatedAt: raw.updated_at ?? '',
  }
}

export function useStorySandboxBranches(novelId: string, chapter: number) {
  return useQuery({
    queryKey: storySandboxBranchesKey(novelId, chapter),
    queryFn: async (): Promise<SandboxBranch[]> => {
      const params = new URLSearchParams({ chapter: String(chapter), novel_id: novelId })
      const res = await fetch(`/api/story-sandbox/branches?${params}`)
      const body = await res.json().catch(() => ({}))
      const raw = Array.isArray((body as { branches?: unknown[] }).branches)
        ? (body as { branches: Parameters<typeof parseBranch>[0][] }).branches
        : []
      return raw.map(parseBranch)
    },
    enabled: !!novelId,
  })
}

export function useCreateStorySandboxBranch(novelId: string, chapter: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (args?: { name?: string; sourceBranchId?: string }): Promise<SandboxBranch> => {
      const res = await fetch('/api/story-sandbox/branches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chapter, name: args?.name, source_branch_id: args?.sourceBranchId,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { error?: string }).error ?? `新建故事线失败 (HTTP ${res.status})`)
      }
      const body = await res.json()
      return parseBranch(body.branch)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: storySandboxBranchesKey(novelId, chapter) })
    },
  })
}

export function useRenameStorySandboxBranch(novelId: string, chapter: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ branchId, name }: { branchId: string; name: string }) => {
      const params = new URLSearchParams({ chapter: String(chapter) })
      const res = await fetch(`/api/story-sandbox/branches/${branchId}?${params}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { error?: string }).error ?? `重命名失败 (HTTP ${res.status})`)
      }
      const body = await res.json()
      return parseBranch(body.branch)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: storySandboxBranchesKey(novelId, chapter) })
    },
  })
}

export function useDeleteStorySandboxBranch(novelId: string, chapter: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (branchId: string): Promise<SandboxBranch> => {
      const params = new URLSearchParams({ chapter: String(chapter) })
      const res = await fetch(`/api/story-sandbox/branches/${branchId}?${params}`, { method: 'DELETE' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { error?: string }).error ?? `删除失败 (HTTP ${res.status})`)
      }
      const body = await res.json()
      return parseBranch(body.branch)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: storySandboxBranchesKey(novelId, chapter) })
    },
  })
}

export function useResetStorySandboxBranch(novelId: string, chapter: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (branchId: string): Promise<SandboxBranch> => {
      const params = new URLSearchParams({ chapter: String(chapter) })
      const res = await fetch(`/api/story-sandbox/branches/${branchId}/reset?${params}`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { error?: string }).error ?? `重置失败 (HTTP ${res.status})`)
      }
      const body = await res.json()
      return parseBranch(body.branch)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: storySandboxBranchesKey(novelId, chapter) })
    },
  })
}

export function useSandboxCastArchives(novelId: string, chapter: number, names: string[]) {
  const sortedNames = [...names].sort()
  return useQuery({
    queryKey: sandboxCastArchivesKey(novelId, chapter, sortedNames.join(',')),
    queryFn: () => fetchSandboxCastArchives(chapter, sortedNames, novelId),
    enabled: !!novelId,
  })
}

export function useSandboxRelatedCastArchives(novelId: string, chapter: number, present: string[]) {
  const sortedNames = [...present].sort()
  return useQuery({
    queryKey: sandboxRelatedCastArchivesKey(novelId, chapter, sortedNames.join(',')),
    queryFn: () => fetchSandboxRelatedCastArchives(chapter, sortedNames, novelId),
    enabled: !!novelId,
  })
}

export function useSandboxMemoryArchive(novelId: string, chapter: number, branchId: string | null) {
  return useQuery({
    queryKey: sandboxMemoryArchiveKey(novelId, chapter, branchId ?? ''),
    queryFn: () => fetchSandboxMemoryArchive(chapter, branchId),
    enabled: !!novelId,
  })
}
