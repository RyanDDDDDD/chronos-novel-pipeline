import type { AppDispatch } from '@/shared/store/store'
import { novelStatusSnapshotLoaded } from '@/shared/store/novelStatusSlice'
import { backgroundJobsSnapshotLoaded } from '@/shared/store/backgroundJobsSlice'

export type NovelStatusSnapshot = Record<string, {
  author_loop: boolean
  setup_chat: boolean
  story_sandbox: boolean
  skeleton_review: boolean
  timeline_cascade: boolean
  world_review: boolean
  character_review: boolean
}>

/** Pulls backend SSOT for per-novel run + background-job flags into Redux. Used on app mount
 * and again on WS reconnect so a missed *_done event cannot leave stale toasts forever. */
export async function loadNovelStatusSnapshot(dispatch: AppDispatch): Promise<NovelStatusSnapshot> {
  const res = await fetch('/api/novels/status')
  const data = await res.json() as NovelStatusSnapshot
  dispatch(novelStatusSnapshotLoaded(data))
  dispatch(backgroundJobsSnapshotLoaded(data))
  return data
}
