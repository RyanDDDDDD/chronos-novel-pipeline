export interface ReviewHookCard {
  name: string
  content: string | null
}

export async function fetchReviewHookCard(name: string): Promise<ReviewHookCard | null> {
  const res = await fetch(`/api/author-loop/review-hooks/${encodeURIComponent(name)}`)
  if (!res.ok) return null
  const body = await res.json().catch(() => ({}))
  return { name, content: typeof body.content === 'string' ? body.content : null }
}
