import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDispatch } from 'react-redux'
import { useNavigate, useLocation, useParams } from 'react-router-dom'
import { fetchNovels, createNovel, copyNovel, renameNovel, deleteNovel, setNovelPinned, type Novel } from '@/shared/utils/novels'
import { novelsKey } from '@/shared/queries/keys'
import { viewFromPathname } from '@/shared/utils/novelRoute'
import { useToast } from '@/shared/hooks/useToast'
import type { AppDispatch } from '@/shared/store/store'
import { loadNovelStatusSnapshot } from '@/shared/queries/novelStatusSnapshot'

export function useNovels() {
  return useQuery({ queryKey: novelsKey, queryFn: fetchNovels })
}

//Active novel id = single source of per-novel query key; no active novel space-time string (downstream enabled:!!id is naturally not checked).
export function useActiveNovelId(): string {
  const { data } = useNovels()
  return data?.find((n) => n.active)?.id ?? ''
}

export type { NovelStatusSnapshot } from '@/shared/queries/novelStatusSnapshot'
export { loadNovelStatusSnapshot } from '@/shared/queries/novelStatusSnapshot'

export function useNovelStatusSnapshot() {
  const dispatch = useDispatch<AppDispatch>()
  return useQuery({
    queryKey: ['novels', 'status'],
    queryFn: () => loadNovelStatusSnapshot(dispatch),
    staleTime: Infinity,
  })
}

/** Mutation + toast + navigate composition for novel create/copy/rename/delete, migrated
 * verbatim out of App.tsx's handleCreateNovel/handleCopyNovel/handleRenameNovel/handleDeleteNovel
 * so NovelRail can call it directly. handleSwitchNovel (pure navigate(), no mutation) is NOT
 * here -- NovelRail writes that one line itself with useNavigate. */
export function useNovelActions(): {
  createNovel: () => Promise<void>
  copyNovel: (sourceId: string) => Promise<void>
  renameNovel: (targetId: string) => Promise<void>
  deleteNovel: (targetId: string) => Promise<void>
  togglePinNovel: (targetId: string) => Promise<void>
} {
  const navigate = useNavigate()
  const location = useLocation()
  const novelId = useParams().novelId ?? ''
  const currentView = viewFromPathname(location.pathname)
  const queryClient = useQueryClient()
  const { data: novels = [] } = useNovels()
  const { success, error: toastError, confirm, prompt } = useToast()

  const createNovelAction = useCallback(async () => {
    const name = await prompt('新小说名称', { placeholder: '请输入小说名称', confirmLabel: '创建' })
    if (!name) return
    const r = await createNovel(name, false)
    if (!r.ok || !r.id) { toastError(r.error ?? '新建失败'); return }
    await queryClient.refetchQueries({ queryKey: ['novels'] })
    navigate(`/novel/${r.id}/chat`)
  }, [queryClient, navigate, toastError, prompt])

  const copyNovelAction = useCallback(async (sourceId: string) => {
    const src = novels.find((n) => n.id === sourceId)
    const defaultName = `${src?.name ?? '小说'} 副本`
    const name = await prompt('复制为', {
      defaultValue: defaultName,
      placeholder: '请输入副本名称',
      confirmLabel: '复制',
    })
    if (!name) return
    const r = await copyNovel(sourceId, name)
    if (!r.ok || !r.id) { toastError(r.error ?? '复制失败'); return }
    await queryClient.refetchQueries({ queryKey: novelsKey })
    success('已复制')
    navigate(`/novel/${r.id}/chat`)
  }, [novels, queryClient, navigate, success, toastError, prompt])

  const renameNovelAction = useCallback(async (targetId: string) => {
    if (!targetId) return
    const cur = novels.find((n) => n.id === targetId)?.name ?? ''
    const name = await prompt('重命名小说', {
      defaultValue: cur,
      placeholder: '请输入新名称',
      confirmLabel: '保存',
    })
    if (!name || name === cur) return
    const r = await renameNovel(targetId, name)
    if (!r.ok) { toastError(r.error ?? '重命名失败'); return }
    await queryClient.invalidateQueries({ queryKey: novelsKey })
    success('已重命名')
  }, [novels, queryClient, success, toastError, prompt])

  const deleteNovelAction = useCallback(async (targetId: string) => {
    if (!targetId) return
    const targetName = novels.find((n) => n.id === targetId)?.name ?? ''
    if (!(await confirm(`删除《${targetName}》？此操作不可撤销。`))) return
    const r = await deleteNovel(targetId)
    if (!r.ok) { toastError(r.error ?? '删除失败'); return }
    await queryClient.refetchQueries({ queryKey: ['novels'] })
    // Only navigate away if the novel we're currently viewing was the one just deleted.
    if (targetId === novelId) {
      const fresh = (queryClient.getQueryData(novelsKey) as Novel[] | undefined) ?? []
      const newActive = fresh.find((n) => n.active)?.id ?? fresh[0]?.id
      if (newActive) navigate(`/novel/${newActive}/${currentView}`)
    }
  }, [novels, novelId, queryClient, navigate, currentView, toastError, confirm])

  const togglePinNovelAction = useCallback(async (targetId: string) => {
    const target = novels.find((n) => n.id === targetId)
    if (!target) return
    const r = await setNovelPinned(targetId, !target.pinned)
    if (!r.ok) { toastError(r.error ?? (target.pinned ? '取消置顶失败' : '置顶失败')); return }
    await queryClient.invalidateQueries({ queryKey: novelsKey })
  }, [novels, queryClient, toastError])

  return {
    createNovel: createNovelAction, copyNovel: copyNovelAction,
    renameNovel: renameNovelAction, deleteNovel: deleteNovelAction,
    togglePinNovel: togglePinNovelAction,
  }
}
