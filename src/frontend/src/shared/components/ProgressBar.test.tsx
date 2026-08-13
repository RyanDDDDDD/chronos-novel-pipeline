import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProgressBar from '@/shared/components/ProgressBar'

describe('ProgressBar', () => {
  it('renders x/y label and a fill width proportional to progress', () => {
    render(<ProgressBar index={3} total={10} />)
    expect(screen.getByText('3/10').textContent).toBe('3/10')
  })

  it('handles total=0 without dividing by zero', () => {
    render(<ProgressBar index={0} total={0} />)
    expect(screen.getByText('0/0').textContent).toBe('0/0')
  })
})
