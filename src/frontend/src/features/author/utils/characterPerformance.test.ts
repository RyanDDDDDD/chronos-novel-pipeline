import { describe, expect, it } from 'vitest'
import { parseCharacterPerformance, resolveCharacterSegment } from './characterPerformance'

describe('parseCharacterPerformance', () => {
  it('parses complete JSON', () => {
    expect(parseCharacterPerformance(
      '{"dialogue":"嗯","intent":"扬手","psychology":"心虚"}',
    )).toEqual({
      dialogue: '嗯', intent: '扬手', psychology: '心虚', fromJson: true,
    })
  })

  it('extracts partial dialogue while streaming', () => {
    expect(parseCharacterPerformance('{"dialogue":"你好世')).toEqual({
      dialogue: '你好世', intent: '', psychology: '', fromJson: true,
    })
  })

  it('extracts multiple keys from partial stream', () => {
    const r = parseCharacterPerformance('{"dialogue":"台词","intent":"动手","psychology":"慌')
    expect(r?.dialogue).toBe('台词')
    expect(r?.intent).toBe('动手')
    expect(r?.psychology).toBe('慌')
  })

  it('returns null for plain prose', () => {
    expect(parseCharacterPerformance('纯台词')).toBeNull()
  })
})

describe('resolveCharacterSegment', () => {
  it('uses split fields when present', () => {
    expect(resolveCharacterSegment({
      text: '台词', intent: '动作', psychology: '心理',
    })).toEqual({ dialogue: '台词', intent: '动作', psychology: '心理' })
  })

  it('parses JSON blob in text when fields empty', () => {
    expect(resolveCharacterSegment({
      text: '{"dialogue":"a","intent":"b","psychology":"c"}',
      intent: '', psychology: '',
    })).toEqual({ dialogue: 'a', intent: 'b', psychology: 'c' })
  })
})
