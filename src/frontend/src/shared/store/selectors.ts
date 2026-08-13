import type { RootState } from '@/shared/store/store'

export const selectBusy = (state: RootState): boolean =>
  state.authorLoop.status === 'running'

export const selectResumable = (chapter: number) => (state: RootState): boolean =>
  state.authorLoop.resumableChapters.includes(chapter)
