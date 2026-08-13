import { describe, expect, it } from 'vitest'
import { filterCharactersByName } from './filterCharactersByName'

describe('filterCharactersByName', () => {
  const chars = [{ name: '林晚' }, { name: 'Alice' }, { name: '林清' }]

  it('returns all when query is empty or whitespace', () => {
    expect(filterCharactersByName(chars, '')).toEqual(chars)
    expect(filterCharactersByName(chars, '   ')).toEqual(chars)
  })

  it('matches name substring case-insensitively', () => {
    expect(filterCharactersByName(chars, '林')).toEqual([{ name: '林晚' }, { name: '林清' }])
    expect(filterCharactersByName(chars, 'alice')).toEqual([{ name: 'Alice' }])
    expect(filterCharactersByName(chars, 'ALICE')).toEqual([{ name: 'Alice' }])
  })

  it('returns empty when nothing matches', () => {
    expect(filterCharactersByName(chars, '不存在')).toEqual([])
  })

  it('trims query before matching', () => {
    expect(filterCharactersByName(chars, '  林晚  ')).toEqual([{ name: '林晚' }])
  })
})
