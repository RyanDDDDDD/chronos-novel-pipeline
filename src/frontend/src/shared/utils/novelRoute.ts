import type { Novel } from '@/shared/utils/novels'

export type View = 'pipeline' | 'author' | 'manuscript' | 'setup' | 'chat' | 'sandbox' | 'services' | 'stats'

/** All routable top-level views (pathname 第 3 段合法性校验). */
export const VIEWS: View[] = ['pipeline', 'author', 'manuscript', 'chat', 'sandbox', 'setup', 'services', 'stats']

/** 顶栏 view tab 文案 SSOT（Header 与各路由跳转共用）。 */
export const VIEW_LABELS: Record<View, string> = {
  pipeline: '流水线',
  author: '主笔',
  manuscript: '成稿',
  setup: '设定',
  chat: '对话',
  sandbox: '故事沙盒',
  services: '服务',
  stats: '统计',
}

/** 设定页子页——真实子路由 /setup/<tab>，不再是 Redux 状态。 */
export type SetupTab = 'world' | 'cast' | 'plot' | 'archives' | 'attachments'

export const SETUP_TABS: SetupTab[] = ['world', 'cast', 'plot', 'archives', 'attachments']

export const SETUP_TAB_LABELS: Record<SetupTab, string> = {
  world: '世界观',
  cast: '人物',
  plot: '故事',
  archives: '角色档案',
  attachments: '附件解析',
}

/** 流水线编排页 workflow 图三个 tab（/pipeline?tab=…）。 */
export type WorkflowTab = 'runtime' | 'skeleton' | 'sandbox'

export const WORKFLOW_TABS: WorkflowTab[] = ['runtime', 'skeleton', 'sandbox']

export const WORKFLOW_TAB_LABELS: Record<WorkflowTab, string> = {
  runtime: '主笔',
  skeleton: '对话',
  sandbox: '故事沙盒',
}

/** ?tab= 非法或缺失时默认「主笔」图。 */
export function workflowTabFromSearch(search: string): WorkflowTab {
  const tab = new URLSearchParams(search).get('tab')
  return tab && (WORKFLOW_TABS as string[]).includes(tab) ? (tab as WorkflowTab) : 'runtime'
}

export interface NovelSwitchResult {
  action: 'none' | 'switch' | 'redirect'
  target?: string
}

/**
 *Decide what to do with "novelId in URL" versus "backend single-active":
 *- The list is empty (not loaded) → none, wait for loading, do not misjudge it to be illegal.
 *- Illegal/missing id → redirect back to active (or first).
 *- id is valid but not active → switch.
 *- id is active → none.
 */
export function resolveNovelSwitch(
  urlNovelId: string | undefined,
  novels: Novel[],
): NovelSwitchResult {
  if (novels.length === 0) return { action: 'none' }
  const active = novels.find((n) => n.active)?.id ?? novels[0].id
  if (!urlNovelId || !novels.some((n) => n.id === urlNovelId)) {
    return { action: 'redirect', target: active }
  }
  if (urlNovelId !== active) return { action: 'switch', target: urlNovelId }
  return { action: 'none' }
}

/** The 4th paragraph of /novel/:id/<view> is the view; missing/illegal pipeline.*/
export function viewFromPathname(pathname: string): View {
  const seg = pathname.split('/')[3] as View | undefined
  return seg && VIEWS.includes(seg) ? seg : 'pipeline'
}

/** pathname 第 3 段是 'setup' 时，取第 4 段作为设定子页；否则（不在 /setup 下，或子页非法）null。 */
export function setupTabFromPathname(pathname: string): SetupTab | null {
  const parts = pathname.split('/')
  if (parts[3] !== 'setup') return null
  const tab = parts[4]
  return tab && (SETUP_TABS as string[]).includes(tab) ? (tab as SetupTab) : null
}
