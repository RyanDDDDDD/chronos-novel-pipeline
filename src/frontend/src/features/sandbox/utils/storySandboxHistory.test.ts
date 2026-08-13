import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchStorySandboxHistory } from '@/features/sandbox/utils/storySandboxHistory'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    json: () => Promise.resolve(body),
  }))
}

describe('fetchStorySandboxHistory', () => {
  it('maps event_log_entries and legacy event_log_entry to eventLogEntries', async () => {
    stubFetch({
      rounds: [
        { instruction: '继续', prose: '正文', event_log_entries: [{ summary: '甲做了事', time: '之后' }] },
        { instruction: '旧', prose: '旧正文', event_log_entry: { summary: '旧事件', time: '上午' } },
      ],
    })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].eventLogEntries).toEqual([{ summary: '甲做了事', time: '之后' }])
    expect(history.rounds[1].eventLogEntries).toEqual([{ summary: '旧事件', time: '上午' }])
  })

  it('defaults eventLogEntries to empty when the round produced no events', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].eventLogEntries).toEqual([])
  })

  it('maps rolling_summary_after to rollingSummaryAfter when present', async () => {
    stubFetch({
      rounds: [{ instruction: '继续', prose: '正文', rolling_summary_after: '目前为止的摘要' }],
    })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].rollingSummaryAfter).toBe('目前为止的摘要')
  })

  it('defaults rollingSummaryAfter to empty string when absent', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].rollingSummaryAfter).toBe('')
  })

  it('maps recall_context to recallContext when present', async () => {
    stubFetch({
      rounds: [{ instruction: '继续', prose: '正文', recall_context: '## 相关历史/设定回收\n- 甲做了事' }],
    })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].recallContext).toBe('## 相关历史/设定回收\n- 甲做了事')
  })

  it('defaults recallContext to empty string when absent', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].recallContext).toBe('')
  })

  it('maps profile_mutation to profileMutation', async () => {
    stubFetch({
      rounds: [{
        instruction: '继续', prose: '正文',
        profile_mutation: { 甲: { race: '精灵' } },
      }],
    })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].profileMutation).toEqual({ 甲: { race: '精灵' } })
  })

  it('defaults profileMutation to null when absent', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.rounds[0].profileMutation).toBeNull()
  })

  it('maps active_cast from the history response', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }], active_cast: ['乙', '甲'] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.active_cast).toEqual(['乙', '甲'])
  })

  it('defaults active_cast to [] when absent', async () => {
    stubFetch({ rounds: [{ instruction: '继续', prose: '正文' }] })
    const history = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')
    expect(history.active_cast).toEqual([])
  })

  it('returns [] when novelId is empty', async () => {
    stubFetch({ rounds: [{ instruction: 'x', prose: 'y' }] })
    expect(await fetchStorySandboxHistory(1, 'branch-a', '')).toEqual({ rounds: [], active_cast: [], liveRound: null })
  })

  it('returns [] on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
    expect(await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')).toEqual({ rounds: [], active_cast: [], liveRound: null })
  })

  it('parses a present live_round into camelCase liveRound', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [], active_cast: [],
        live_round: {
          mode: 'turn', instruction: '继续',
          events: [{ type: 'story_sandbox_token', delta: '甲' }],
        },
      }),
    } as Response)

    const result = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')

    expect(result.liveRound).toEqual({
      mode: 'turn', instruction: '继续',
      events: [{ type: 'story_sandbox_token', delta: '甲' }],
    })
  })

  it('defaults liveRound to null when live_round is absent', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ rounds: [], active_cast: [] }),
    } as Response)

    const result = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')

    expect(result.liveRound).toBeNull()
  })

  it('defaults liveRound to null when live_round is explicitly null', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ rounds: [], active_cast: [], live_round: null }),
    } as Response)

    const result = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')

    expect(result.liveRound).toBeNull()
  })

  it('coerces an unrecognized mode string to "turn"', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [], active_cast: [],
        live_round: { mode: 'bogus', instruction: '', events: [] },
      }),
    } as Response)

    const result = await fetchStorySandboxHistory(1, 'branch-a', 'novel-a')

    expect(result.liveRound?.mode).toBe('turn')
  })
})
