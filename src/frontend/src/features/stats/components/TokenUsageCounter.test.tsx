import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import TokenUsageCounter from '@/features/stats/components/TokenUsageCounter'

describe('TokenUsageCounter', () => {
  it('渲染输入/输出/缓存三项', () => {
    render(
      <TokenUsageCounter
        usage={{ tokens_in: 153_712, tokens_out: 77_621, tokens_cached: 59_776 }}
      />,
    )
    expect(screen.getByText('153,712')).toBeTruthy()
    expect(screen.getByText('77,621')).toBeTruthy()
    expect(screen.getByText('59,776')).toBeTruthy()
    expect(screen.getByText('输入')).toBeTruthy()
    expect(screen.queryByText('成本')).toBeNull()
  })

  it('usage 为空时显示零态', () => {
    render(<TokenUsageCounter usage={null} />)
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(3)
  })
})
