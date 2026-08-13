async function parseMutationResponse<T extends object>(
  res: Response,
): Promise<({ ok: true } & T) | { ok: false; error: string }> {
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body.ok === false) {
    return { ok: false, error: body.error ?? `请求失败 (HTTP ${res.status})` }
  }
  return { ok: true, ...body } as { ok: true } & T
}

export async function regenerateCastPortrait(
  name: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch('/api/character-portrait/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_name: name }),
  })
  return parseMutationResponse(res)
}
