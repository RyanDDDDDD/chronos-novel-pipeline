import { describe, expect, it } from 'vitest'
import { sortCharactersByName } from './sortCharactersByName'

describe('sortCharactersByName', () => {
  it('sorts by name ascending', () => {
    const chars = [{ name: '林晚' }, { name: 'Alice' }, { name: '林清' }]
    expect(sortCharactersByName(chars).map((c) => c.name)).toEqual(
      [...chars.map((c) => c.name)].sort((a, b) => a.localeCompare(b)),
    )
  })

  it('does not mutate the input array', () => {
    const chars = [{ name: 'Zed' }, { name: 'Amy' }]
    const original = [...chars]
    sortCharactersByName(chars)
    expect(chars).toEqual(original)
  })

  it('preserves other fields on each character', () => {
    const chars = [{ name: 'B', portrait_path: 'b.png' }, { name: 'A', portrait_path: 'a.png' }]
    expect(sortCharactersByName(chars)).toEqual([
      { name: 'A', portrait_path: 'a.png' },
      { name: 'B', portrait_path: 'b.png' },
    ])
  })

  it('is stable regardless of input order (regression: portrait regenerate re-appends a character)', () => {
    const original = [{ name: 'Amy' }, { name: 'Bob' }, { name: 'Cara' }]
    const reappended = [{ name: 'Bob' }, { name: 'Cara' }, { name: 'Amy' }]
    expect(sortCharactersByName(reappended)).toEqual(sortCharactersByName(original))
  })
})
