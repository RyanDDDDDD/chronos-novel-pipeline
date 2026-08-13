import { describe, it, expect, vi } from 'vitest'
import { fetchCast, fetchSetupChatHistory } from './setup'

describe('fetchCast', () => {
  it('sorts the returned roster by name regardless of API/storage order', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({
        characters: [{ name: 'Cara' }, { name: 'Amy' }, { name: 'Bob' }],
      }),
    } as Response)

    const result = await fetchCast()

    expect(result.map((c) => c.name)).toEqual(['Amy', 'Bob', 'Cara'])
  })

  it('defaults to an empty array when characters is absent', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({ json: async () => ({}) } as Response)

    expect(await fetchCast()).toEqual([])
  })
})

describe('fetchSetupChatHistory', () => {
  it('parses a present live_round into camelCase liveRound', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({
        messages: [],
        live_round: { instruction: '继续', events: [{ type: 'setup_chat_token', delta: '甲' }] },
      }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.liveRound).toEqual({
      instruction: '继续', events: [{ type: 'setup_chat_token', delta: '甲' }],
    })
  })

  it('passes novel_id query param', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({ messages: [] }),
    } as Response)
    await fetchSetupChatHistory('novel-b')
    expect(fetchSpy).toHaveBeenCalledWith('/api/setup-chat/history?novel_id=novel-b')
  })

  it('defaults liveRound to null when live_round is absent', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({ messages: [] }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.liveRound).toBeNull()
  })

  it('defaults liveRound to null when live_round is explicitly null', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({ messages: [], live_round: null }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.liveRound).toBeNull()
  })

  it('still parses messages unchanged', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({ messages: [{ id: 'm1', role: 'user', content: 'hi' }] }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.messages).toEqual([{ id: 'm1', role: 'user', content: 'hi' }])
  })
})

describe('fetchSetupChatHistory choice records', () => {
  it('preserves options on a choice-role message', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({
        messages: [{ id: 'c1', role: 'choice', content: '继续吗？', options: ['是', '否'] }],
      }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.messages).toEqual([
      { id: 'c1', role: 'choice', content: '继续吗？', options: ['是', '否'] },
    ])
  })

  it('omits options for non-choice messages', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      json: async () => ({ messages: [{ id: 'm1', role: 'user', content: 'hi' }] }),
    } as Response)

    const result = await fetchSetupChatHistory('novel-a')

    expect(result.messages[0]).not.toHaveProperty('options')
  })
})
