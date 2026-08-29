/** Plain fetch helpers for the sandbox scene-image feature -- deliberately not react-query
 * hooks: the image map is fetched once per scope and refreshed on the WS done event, same
 * lightweight pattern as the memory-archive panel. */

export async function fetchSceneImages(
  chapter: number, branchId: string,
): Promise<Record<string, string>> {
  try {
    const res = await fetch(
      `/api/story-sandbox/scene-images?chapter=${chapter}&branch_id=${encodeURIComponent(branchId)}`,
    )
    const body = await res.json().catch(() => ({}))
    return body && typeof body.images === 'object' && body.images ? body.images : {}
  } catch {
    return {}
  }
}

export async function requestSceneImage(
  chapter: number, branchId: string, roundId: string,
): Promise<{ ok: boolean }> {
  try {
    const res = await fetch('/api/story-sandbox/scene-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter, branch_id: branchId, round_id: roundId }),
    })
    return await res.json().catch(() => ({ ok: false }))
  } catch {
    return { ok: false }
  }
}
