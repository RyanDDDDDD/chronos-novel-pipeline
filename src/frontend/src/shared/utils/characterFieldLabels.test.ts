import { describe, it, expect } from 'vitest'
import {
  characterProfileFieldLabel,
  formatGenderLabel,
  formatProfileScalarDisplay,
} from './characterFieldLabels'

describe('characterFieldLabels', () => {
  it('maps known profile field keys to Chinese labels', () => {
    expect(characterProfileFieldLabel('identity_background')).toBe('身份背景')
    expect(characterProfileFieldLabel('personality')).toBe('性格')
    expect(characterProfileFieldLabel('unknown_key')).toBe('unknown_key')
  })

  it('formats gender enum values', () => {
    expect(formatGenderLabel('female')).toBe('女')
    expect(formatGenderLabel('male')).toBe('男')
    expect(formatGenderLabel('other')).toBe('other')  // unmapped/pack-only gender falls back to raw value
  })

  it('formatProfileScalarDisplay applies gender mapping only for gender field', () => {
    expect(formatProfileScalarDisplay('gender', 'male')).toBe('男')
    expect(formatProfileScalarDisplay('race', '精灵')).toBe('精灵')
  })
})
