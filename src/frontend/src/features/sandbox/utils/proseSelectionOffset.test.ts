// @vitest-environment jsdom
// This module walks real DOM nodes/Range objects -- this repo's environmentMatchGlobs only
// grants jsdom to .test.tsx files by default, so a plain .test.ts needs this per-file override.
import { describe, it, expect } from 'vitest'
import { reconstructPlainText, computeSelectionOffset } from './proseSelectionOffset'

function buildProse(): HTMLDivElement {
  const div = document.createElement('div')
  const p1 = document.createElement('p')
  p1.textContent = '甲抬起头，看向窗外。'
  const p2 = document.createElement('p')
  p2.textContent = '乙站起身，走向门口。'
  div.append(p1, p2)
  document.body.appendChild(div)
  return div
}

describe('reconstructPlainText', () => {
  it('joins sibling paragraphs with a blank line, mirroring markdown source', () => {
    const div = buildProse()
    expect(reconstructPlainText(div)).toBe('甲抬起头，看向窗外。\n\n乙站起身，走向门口。')
  })

  it('returns a single paragraph as-is with no separator', () => {
    const div = document.createElement('div')
    const p = document.createElement('p')
    p.textContent = '甲抬起头。'
    div.appendChild(p)
    expect(reconstructPlainText(div)).toBe('甲抬起头。')
  })

  it('keeps inline formatting text contiguous within one paragraph', () => {
    const div = document.createElement('div')
    const p = document.createElement('p')
    const strong = document.createElement('strong')
    strong.textContent = '甲抬起头'
    p.append(strong, document.createTextNode('，看向窗外。'))
    div.appendChild(p)
    expect(reconstructPlainText(div)).toBe('甲抬起头，看向窗外。')
  })
})

describe('computeSelectionOffset', () => {
  it('computes the offset of a selection start in the first paragraph', () => {
    const div = buildProse()
    const textNode = div.querySelector('p')!.firstChild as Text
    const range = document.createRange()
    const start = textNode.data.indexOf('看向窗外')
    range.setStart(textNode, start)
    range.setEnd(textNode, start + 4)
    expect(computeSelectionOffset(div, range)).toBe(start)
  })

  it('computes the offset of a selection start in the second paragraph, past the blank-line separator', () => {
    const div = buildProse()
    const secondTextNode = div.querySelectorAll('p')[1].firstChild as Text
    const start = secondTextNode.data.indexOf('走向门口')
    const range = document.createRange()
    range.setStart(secondTextNode, start)
    range.setEnd(secondTextNode, start + 4)
    const firstParaLen = '甲抬起头，看向窗外。'.length
    expect(computeSelectionOffset(div, range)).toBe(firstParaLen + 2 + start) // +2 for the '\n\n'
  })

  it('returns 0 when the selection starts at the very beginning of the container', () => {
    const div = buildProse()
    const textNode = div.querySelector('p')!.firstChild as Text
    const range = document.createRange()
    range.setStart(textNode, 0)
    range.setEnd(textNode, 1)
    expect(computeSelectionOffset(div, range)).toBe(0)
  })
})
