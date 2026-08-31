import { useQuery } from '@tanstack/react-query'
import { authorSceneImagesKey } from '@/shared/queries/keys'

/** Per-chapter map of `<stageIndex>` -> scene-image URL. Refetched on the
 * `author_scene_image_done` WS event via a listener in shared/store/listeners.ts
 * (same pattern as portrait generation invalidating the cast query). */
export function useAuthorSceneImages(novelId: string, chapter: number) {
  return useQuery({
    queryKey: authorSceneImagesKey(novelId, chapter),
    queryFn: async (): Promise<Record<string, string>> => {
      const res = await fetch(`/api/author-loop/scene-images?chapter=${chapter}`)
      const body = await res.json().catch(() => ({}))
      return body && typeof body.images === 'object' && body.images ? body.images : {}
    },
    enabled: chapter >= 1,
  })
}

export async function requestAuthorSceneImage(
  chapter: number, index: number,
): Promise<{ ok: boolean }> {
  try {
    const res = await fetch('/api/author-loop/scene-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter, index }),
    })
    return await res.json().catch(() => ({ ok: false }))
  } catch {
    return { ok: false }
  }
}
