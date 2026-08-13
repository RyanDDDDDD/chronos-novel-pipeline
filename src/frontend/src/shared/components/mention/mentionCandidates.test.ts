import { describe, it, expect } from 'vitest'
import {
  findMentionQuery, filterMentionCandidates, applyMentionSelection, detectRecognizedNames,
  type MentionCandidate,
} from './mentionCandidates'

describe('findMentionQuery', () => {
  it('光标紧跟在 @ 之后，query 为空字符串', () => {
    expect(findMentionQuery('@', 1)).toEqual({ start: 0, end: 1, query: '' })
  })

  it('光标在 @xxx 片段中间/末尾，返回已输入的部分', () => {
    const value = '找 @小明 帮忙'
    // "@小明" 在 index 2-5（@=2, 小=3, 明=4），光标落在 "明" 之后 = index 5
    expect(findMentionQuery(value, 5)).toEqual({ start: 2, end: 5, query: '小明' })
  })

  it('@ 与光标之间有空白，不算在 mention 片段内', () => {
    const value = '@小明 你好'
    // 光标落在最后（"好" 之后），@小明 和光标之间隔了一个空格
    expect(findMentionQuery(value, value.length)).toBeNull()
  })

  it('文本里没有 @，返回 null', () => {
    expect(findMentionQuery('随便写点什么', 4)).toBeNull()
  })

  it('多个 @，只认光标前最近的那个', () => {
    const value = '@甲 和 @乙'
    // 光标在末尾（"乙" 之后）
    const cursor = value.length
    const start = value.lastIndexOf('@')
    expect(findMentionQuery(value, cursor)).toEqual({ start, end: cursor, query: '乙' })
  })
})

describe('filterMentionCandidates', () => {
  const candidates: MentionCandidate[] = [
    { name: '橘花音', type: 'character' },
    { name: '苏晚晴', type: 'character' },
    { name: '高桥美咲', type: 'character' },
  ]

  it('空 query 返回全部', () => {
    expect(filterMentionCandidates(candidates, '')).toEqual(candidates)
  })

  it('按 name 子串过滤', () => {
    expect(filterMentionCandidates(candidates, '晴')).toEqual([{ name: '苏晚晴', type: 'character' }])
  })

  it('无匹配返回空数组', () => {
    expect(filterMentionCandidates(candidates, '不存在')).toEqual([])
  })
})

describe('applyMentionSelection', () => {
  it('把 [start,end) 片段替换成 "@全名 "，光标落在插入内容之后', () => {
    const value = '找 @小明 帮忙'
    const result = applyMentionSelection(value, 2, 5, '橘花音')
    expect(result.value).toBe('找 @橘花音 帮忙')
    expect(result.cursor).toBe(2 + '@橘花音 '.length)
  })
})

describe('detectRecognizedNames', () => {
  const names = ['橘花音', '苏晚晴']

  it('文本为空返回空数组', () => {
    expect(detectRecognizedNames('', names)).toEqual([])
  })

  it('返回文本里命中的已知角色名，保持 names 顺序', () => {
    expect(detectRecognizedNames('苏晚晴拉着橘花音的手', names)).toEqual(['橘花音', '苏晚晴'])
  })

  it('没有命中返回空数组', () => {
    expect(detectRecognizedNames('路人甲说了什么', names)).toEqual([])
  })
})
