import { useNavigate, useLocation, useParams } from 'react-router-dom'
import {
  Workflow,
  PenLine,
  Settings,
  MessageSquare,
  Sparkles,
  Server,
  BarChart3,
  Globe,
  Users,
  BookOpen,
  Contact,
  ChevronDown,
  ImageIcon,
  type LucideIcon,
} from 'lucide-react'
import {
  VIEW_LABELS, SETUP_TAB_LABELS, WORKFLOW_TAB_LABELS,
  viewFromPathname, setupTabFromPathname, workflowTabFromSearch,
  type View, type SetupTab, type WorkflowTab,
} from '@/shared/utils/novelRoute'
import { isNotifyView, type ViewUnreadState, type NotifyView } from '@/shared/utils/viewUnreadBadges'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
} from '@/shared/components/ui/dropdown-menu'

type NavLeaf =
  | { kind: 'view'; view: View }
  | { kind: 'setupTab'; tab: SetupTab }
  | { kind: 'workflowTab'; tab: WorkflowTab }

interface NavGroup {
  kind: 'group'
  key: string
  label: string
  icon: LucideIcon
  /** Dropdown anchor: end = align to trigger's right edge (better for right-side groups). */
  menuAlign?: 'start' | 'end'
  children: NavLeaf[]
}

interface NavFlat {
  kind: 'flat'
  view: View
}

type NavEntry = NavGroup | NavFlat

const VIEW_ICONS: Partial<Record<View, LucideIcon>> = {
  pipeline: Workflow,
  chat: MessageSquare,
  author: PenLine,
  sandbox: Sparkles,
  services: Server,
  stats: BarChart3,
}

const SETUP_TAB_ICONS: Record<SetupTab, LucideIcon> = {
  world: Globe,
  cast: Users,
  plot: BookOpen,
  archives: Contact,
  attachments: ImageIcon,
}

const WORKFLOW_TAB_ICONS: Record<WorkflowTab, LucideIcon> = {
  runtime: PenLine,
  skeleton: MessageSquare,
  sandbox: Sparkles,
}

const NAV_ENTRIES: NavEntry[] = [
  {
    kind: 'group', key: 'pipeline-group', label: '流水线', icon: Workflow,
    children: [
      { kind: 'workflowTab', tab: 'skeleton' },
      { kind: 'workflowTab', tab: 'runtime' },
      { kind: 'workflowTab', tab: 'sandbox' },
    ],
  },
  { kind: 'flat', view: 'chat' },
  { kind: 'flat', view: 'author' },
  { kind: 'flat', view: 'sandbox' },
  {
    kind: 'group', key: 'setup-group', label: '设定', icon: Settings, menuAlign: 'end',
    children: [
      { kind: 'setupTab', tab: 'world' },
      { kind: 'setupTab', tab: 'cast' },
      { kind: 'setupTab', tab: 'plot' },
      { kind: 'setupTab', tab: 'archives' },
      { kind: 'setupTab', tab: 'attachments' },
    ],
  },
  { kind: 'flat', view: 'services' },
  { kind: 'flat', view: 'stats' },
]

function leafLabel(leaf: NavLeaf): string {
  if (leaf.kind === 'view') return VIEW_LABELS[leaf.view]
  if (leaf.kind === 'workflowTab') return WORKFLOW_TAB_LABELS[leaf.tab]
  return SETUP_TAB_LABELS[leaf.tab]
}

function leafIcon(leaf: NavLeaf): LucideIcon {
  if (leaf.kind === 'view') return VIEW_ICONS[leaf.view] ?? Workflow
  if (leaf.kind === 'workflowTab') return WORKFLOW_TAB_ICONS[leaf.tab]
  return SETUP_TAB_ICONS[leaf.tab]
}

function leafKey(leaf: NavLeaf): string {
  if (leaf.kind === 'view') return leaf.view
  if (leaf.kind === 'workflowTab') return `workflow-${leaf.tab}`
  return `setup-${leaf.tab}`
}

function leafPath(leaf: NavLeaf, novelId: string): string {
  if (leaf.kind === 'view') return `/novel/${novelId}/${leaf.view}`
  if (leaf.kind === 'workflowTab') return `/novel/${novelId}/pipeline?tab=${leaf.tab}`
  return `/novel/${novelId}/setup/${leaf.tab}`
}

function leafNotifyKey(leaf: NavLeaf): NotifyView | null {
  if (leaf.kind === 'setupTab') return leaf.tab === 'archives' ? 'archives' : null
  if (leaf.kind === 'workflowTab') return null
  return isNotifyView(leaf.view) ? leaf.view : null
}

function leafIsActive(leaf: NavLeaf, view: View, setupTab: SetupTab | null, workflowTab: WorkflowTab): boolean {
  if (leaf.kind === 'view') return leaf.view === view
  if (leaf.kind === 'workflowTab') return view === 'pipeline' && workflowTab === leaf.tab
  return view === 'setup' && leaf.tab === setupTab
}

/** Labels hidden below 800px (icon-only); label font steps up only when labels are shown. */
const TOOLBAR_BTN_BASE =
  'flex items-center gap-1 px-1.5 min-[800px]:px-2 py-0.5 rounded-md min-[800px]:text-[11px] lg:text-xs xl:text-sm ' +
  'font-medium transition-[font-size] duration-150 whitespace-nowrap'
const TOOLBAR_LABEL = 'hidden min-[800px]:inline'
const TOOLBAR_ICON = 'shrink-0'

function navItemClass(active: boolean): string {
  return `relative ${TOOLBAR_BTN_BASE} ${
    active
      ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] hover:text-[var(--c-accent-hover)]'
      : 'text-[color:var(--c-text-muted)] hover:bg-[var(--c-surface-hover)] hover:text-[color:var(--c-text-muted)]'
  }`
}

function UnreadDot() {
  return <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-red-500 ring-2 ring-white" aria-hidden />
}

interface Props {
  /** Unread WS activity indicators for author / chat / sandbox / archives tabs. */
  viewUnread?: ViewUnreadState
}

export default function Header({ viewUnread }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const novelId = useParams().novelId ?? ''
  const view = viewFromPathname(location.pathname)
  const setupTab = setupTabFromPathname(location.pathname)
  const workflowTab = workflowTabFromSearch(location.search)

  const go = (leaf: NavLeaf) => navigate(leafPath(leaf, novelId))

  const leafUnread = (leaf: NavLeaf, active: boolean): boolean => {
    const key = leafNotifyKey(leaf)
    return key ? !!viewUnread?.[key] && !active : false
  }

  return (
    <header className="relative z-20 flex flex-col gap-1 px-3 lg:px-4 py-1 bg-white border-b border-slate-200 shrink-0">
      <div className="flex items-center gap-1.5 lg:gap-2 min-w-0 min-h-8">
        <span className="text-sm lg:text-base font-bold text-[color:var(--c-text)] tracking-tight truncate leading-none">
          Chronos 主笔引擎
        </span>
        <nav aria-label="页面导航" className="min-w-0 flex-1 flex justify-end">
          <div className="max-w-full overflow-x-auto overscroll-x-contain scrollbar-hidden">
            <div className="flex items-center justify-end gap-0.5">
              {NAV_ENTRIES.map((entry) => {
                if (entry.kind === 'flat') {
                  const leaf: NavLeaf = { kind: 'view', view: entry.view }
                  const Icon = leafIcon(leaf)
                  const active = leafIsActive(leaf, view, setupTab, workflowTab)
                  const unread = leafUnread(leaf, active)
                  return (
                    <button
                      key={entry.view}
                      type="button"
                      title={leafLabel(leaf)}
                      aria-label={leafLabel(leaf)}
                      onClick={() => go(leaf)}
                      className={navItemClass(active)}
                    >
                      <Icon size={14} className={TOOLBAR_ICON} aria-hidden />
                      <span className={TOOLBAR_LABEL}>{leafLabel(leaf)}</span>
                      {unread && <UnreadDot />}
                    </button>
                  )
                }

                const GroupIcon = entry.icon
                const groupActive = entry.children.some((c) => leafIsActive(c, view, setupTab, workflowTab))
                const groupUnread = entry.children.some((c) => leafUnread(c, leafIsActive(c, view, setupTab, workflowTab)))

                return (
                  <DropdownMenu key={entry.key}>
                    <DropdownMenuTrigger asChild>
                      <button type="button" className={`group ${navItemClass(groupActive)}`} aria-label={entry.label}>
                        <GroupIcon size={14} className={TOOLBAR_ICON} aria-hidden />
                        <span className={TOOLBAR_LABEL}>{entry.label}</span>
                        <ChevronDown
                          size={12}
                          className="relative top-px shrink-0 opacity-70 transition-transform duration-200 group-data-[state=open]:rotate-180"
                          aria-hidden
                        />
                        {groupUnread && <UnreadDot />}
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align={entry.menuAlign ?? 'start'}
                      className="min-w-36 [&_[data-slot=dropdown-menu-item]]:py-1 [&_[data-slot=dropdown-menu-item]]:text-xs [&_[data-slot=dropdown-menu-item]_svg:not([class*='size-'])]:size-3"
                    >
                      {entry.children.map((leaf) => {
                        const Icon = leafIcon(leaf)
                        const active = leafIsActive(leaf, view, setupTab, workflowTab)
                        const unread = leafUnread(leaf, active)
                        return (
                          <DropdownMenuItem
                            key={leafKey(leaf)}
                            onClick={() => go(leaf)}
                            className={
                              active
                                ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] focus:bg-[var(--c-accent-subtle)] focus:text-[var(--c-accent)]'
                                : 'text-[color:var(--c-text-muted)]'
                            }
                          >
                            <Icon className="shrink-0" aria-hidden />
                            {leafLabel(leaf)}
                            {unread && <UnreadDot />}
                          </DropdownMenuItem>
                        )
                      })}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )
              })}
            </div>
          </div>
        </nav>
      </div>
    </header>
  )
}
