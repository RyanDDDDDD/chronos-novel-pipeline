import { describe, it, expect } from 'vitest'
import { SKELETON_EXPANSION_STAGES, SKELETON_EXPANSION_EDGES } from './skeletonExpansionStages'

const EXPECTED_NODE_IDS = [
  'auto_build_setup', 'beat_dialogue_draft', 'character_portrait', 'chat_identity',
  'image_hub', 'image_recognition', 'incremental_relationship', 'prose_style_extraction', 'review',
  'setup_quality_review', 'skeleton_writer', 'text_recognition', 'timeline_derive',
]

describe('skeletonExpansionStages', () => {
  it('十三节点 kinds/labels', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(Object.keys(byId).sort()).toEqual([...EXPECTED_NODE_IDS].sort())
    expect(byId['chat_identity'].kind).toBe('agent-config')
    expect(byId['review'].kind).toBe('review')
    expect(byId['review'].reviewGroup).toBe('buildtime')
    expect(byId['setup_quality_review'].reviewGroup).toBe('setup')
    expect(byId['skeleton_writer'].kind).toBe('mechanism')
    expect(byId['image_hub'].kind).toBe('mechanism')
  })

  it('图片识别/立绘生成经 image_hub 汇入 chat_identity，一键建设定直连', () => {
    expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'image_recognition' && e.target === 'image_hub')).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'character_portrait' && e.target === 'image_hub')).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'image_hub' && e.target === 'chat_identity')).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'image_recognition' && e.target === 'chat_identity')).toBe(false)
    expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'auto_build_setup' && e.target === 'chat_identity')).toBe(true)
  })

  it('三条 hub 链的子节点与链头同 lane', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['text_recognition'].lane).toBe(byId['prose_style_extraction'].lane)
    expect(byId['skeleton_writer'].lane).toBe(byId['beat_dialogue_draft'].lane)
    expect(byId['beat_dialogue_draft'].lane).toBe(byId['review'].lane)
    expect(byId['auto_build_setup'].lane).toBe(byId['setup_quality_review'].lane)
  })

  it('对话 agent 两侧 lane 镜像：hub 行 ±0.5', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['image_recognition']).toMatchObject({ col: 0, lane: -0.5 })
    expect(byId['text_recognition']).toMatchObject({ col: 2, lane: -0.5 })
    expect(byId['prose_style_extraction']).toMatchObject({ col: 3, lane: -0.5 })
    expect(byId['auto_build_setup']).toMatchObject({ col: 0, lane: 0.5 })
    expect(byId['skeleton_writer']).toMatchObject({ col: 2, lane: 0.5 })
    expect(byId['beat_dialogue_draft']).toMatchObject({ col: 3, lane: 0.5 })
    expect(byId['review']).toMatchObject({ col: 4, lane: 0.5 })
    expect(byId['setup_quality_review']).toMatchObject({ col: -1, lane: 0.5 })
    expect(byId['timeline_derive']).toMatchObject({ col: -1, lane: 0 })
    expect(byId['incremental_relationship']).toMatchObject({ col: -1, lane: 1 })
    expect(byId['chat_identity']).toMatchObject({ col: 1, lane: 0 })
    expect(byId['character_portrait']).toMatchObject({ col: 0, lane: -1 })
    expect(byId['image_hub']).toMatchObject({ col: 0.5, lane: -0.5 })
  })

  it('一键建设定与分拍底稿同处 hub 邻接 lane（水平平行）', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['auto_build_setup'].lane).toBe(0.5)
    expect(byId['skeleton_writer'].lane).toBe(0.5)
  })

  it('text_recognition 在对话 agent 右侧，向左接 chat、向右链文风', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['chat_identity'].col).toBe(1)
    expect(byId['text_recognition'].col).toBe(2)
    expect(byId['text_recognition'].lane).toBe(-0.5)
    expect(byId['prose_style_extraction'].col).toBe(3)
    expect(byId['prose_style_extraction'].lane).toBe(-0.5)
  })

  it('text_recognition 接 chat 走右侧 anchor（镜像 auto_build 接 chat）', () => {
    const edge = SKELETON_EXPANSION_EDGES.find(
      e => e.source === 'text_recognition' && e.target === 'chat_identity',
    )
    expect(edge?.sourceHandle).toBe('source-left')
    expect(edge?.targetHandle).toBe('target-right')
  })

  it('text_recognition 链到文风抽取，并向 chat 回流设定', () => {
    expect(SKELETON_EXPANSION_EDGES.filter(e => e.source === 'text_recognition').map(e => e.target).sort())
      .toEqual(['chat_identity', 'prose_style_extraction'])
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'text_recognition' && e.target === 'prose_style_extraction',
    )).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'chat_identity' && e.target === 'prose_style_extraction',
    )).toBe(false)
  })

  it('auto_build_setup 向右接 chat、向左接三路设定建设（两侧分叉）', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['auto_build_setup'].col).toBe(0)
    expect(byId['chat_identity'].col).toBe(1)
    expect(byId['timeline_derive'].col).toBe(-1)
    expect(byId['setup_quality_review'].col).toBe(-1)
    expect(byId['incremental_relationship'].col).toBe(-1)
  })

  it('auto_build_setup 设定建设链统一走左侧 anchor', () => {
    for (const target of ['timeline_derive', 'setup_quality_review', 'incremental_relationship']) {
      const edge = SKELETON_EXPANSION_EDGES.find(
        e => e.source === 'auto_build_setup' && e.target === target,
      )
      expect(edge?.sourceHandle).toBe('source-left')
      expect(edge?.targetHandle).toBe('target-right')
    }
  })

  it('auto_build_setup 分叉到 chat 与三路设定建设节点', () => {
    expect(SKELETON_EXPANSION_EDGES.filter(e => e.source === 'auto_build_setup').map(e => e.target).sort())
      .toEqual(['chat_identity', 'incremental_relationship', 'setup_quality_review', 'timeline_derive'])
    for (const target of ['timeline_derive', 'incremental_relationship']) {
      expect(SKELETON_EXPANSION_EDGES.some(e => e.source === 'chat_identity' && e.target === target)).toBe(false)
    }
  })

  it('chat_identity 仅驱动 skeleton_writer', () => {
    expect(SKELETON_EXPANSION_EDGES.filter(e => e.source === 'chat_identity').map(e => e.target))
      .toEqual(['skeleton_writer'])
  })

  it('chat_identity 下游各节点 lane 互不重复（除链式 beat 与 skeleton_writer 同 lane）', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    const chatTargets = SKELETON_EXPANSION_EDGES
      .filter(e => e.source === 'chat_identity')
      .map(e => byId[e.target].lane)
    expect(new Set(chatTargets).size).toBe(chatTargets.length)
  })

  it('skeleton_writer 链到 beat_dialogue_draft，不再从 chat 直连 beat', () => {
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'skeleton_writer' && e.target === 'beat_dialogue_draft',
    )).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'chat_identity' && e.target === 'beat_dialogue_draft',
    )).toBe(false)
  })

  it('beat_dialogue_draft 链到 review，不再从 chat 直连 review', () => {
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'beat_dialogue_draft' && e.target === 'review',
    )).toBe(true)
    expect(SKELETON_EXPANSION_EDGES.some(
      e => e.source === 'chat_identity' && e.target === 'review',
    )).toBe(false)
  })

  it('十二条边，无 async', () => {
    expect(SKELETON_EXPANSION_EDGES).toHaveLength(12)
    expect(SKELETON_EXPANSION_EDGES.every(e => !e.async)).toBe(true)
  })

  it('col 分层：设定建设-1 ↔ 输入0 ↔ agent1 ↔ 文本2/生成2–3 ↔ 文风3', () => {
    const byId = Object.fromEntries(SKELETON_EXPANSION_STAGES.map(s => [s.id, s]))
    expect(byId['text_recognition'].col).toBe(2)
    expect(byId['text_recognition'].lane).toBe(-0.5)
    expect(byId['prose_style_extraction'].col).toBe(3)
    expect(byId['prose_style_extraction'].lane).toBe(-0.5)
    expect(byId['chat_identity'].col).toBe(1)
    expect(byId['timeline_derive'].col).toBe(-1)
    expect(byId['timeline_derive'].lane).toBe(0)
    expect(byId['setup_quality_review'].col).toBe(-1)
    expect(byId['setup_quality_review'].lane).toBe(0.5)
    expect(byId['incremental_relationship'].col).toBe(-1)
    expect(byId['incremental_relationship'].lane).toBe(1)
    expect(byId['auto_build_setup'].lane).toBe(0.5)
    expect(byId['skeleton_writer'].col).toBe(2)
    expect(byId['beat_dialogue_draft'].col).toBe(3)
    expect(byId['review'].col).toBe(4)
    expect(byId['review'].lane).toBe(0.5)
  })

  it('includes a character_portrait node labeled 立绘生成', () => {
    const node = SKELETON_EXPANSION_STAGES.find(s => s.id === 'character_portrait')
    expect(node).toBeDefined()
    expect(node?.label).toBe('立绘生成')
    expect(node?.kind).toBe('mechanism')
  })

  it('includes an image_hub node labeled 图片, grouping image_recognition + character_portrait', () => {
    const node = SKELETON_EXPANSION_STAGES.find(s => s.id === 'image_hub')
    expect(node).toBeDefined()
    expect(node?.label).toBe('图片')
    expect(node?.kind).toBe('mechanism')
    const inbound = SKELETON_EXPANSION_EDGES.filter(e => e.target === 'image_hub').map(e => e.source).sort()
    expect(inbound).toEqual(['character_portrait', 'image_recognition'])
  })
})
