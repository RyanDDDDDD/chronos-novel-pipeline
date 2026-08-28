import { useState, type ReactNode } from 'react'
import {
  Sun,
  Moon,
  ALargeSmall,
  Sparkles,
  BookMarked,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { useTheme } from '@/shared/hooks/useTheme'
import { useReadingFontSize } from '@/shared/hooks/useReadingFontSize'
import type { ReadingFontSize } from '@/shared/utils/readingFontSize'
import { THEME_LABELS, THEME_ORDER } from '@/shared/utils/theme'
import ProseStylePanel from '@/features/setup/components/ProseStylePanel'
import SourceFranchisePanel from '@/features/setup/components/SourceFranchisePanel'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'

const READING_FONT_SIZE_LABELS: Record<ReadingFontSize, string> = {
  small: '小',
  default: '默认',
  large: '大',
  xlarge: '超大',
}

const READING_FONT_SIZE_ORDER: ReadingFontSize[] = ['small', 'default', 'large', 'xlarge']

type SubMenu = 'theme' | 'font' | 'prose' | 'franchise'

/** Theme / reading font / prose style / source franchise — nested under one「设定」control on the novel rail. */
export default function NovelRailSettings({
  novelId,
  collapsed,
}: {
  novelId: string
  collapsed: boolean
}) {
  const { theme, darkMode, setTheme } = useTheme()
  const { size: fontSize, setSize: setFontSize } = useReadingFontSize()
  const [open, setOpen] = useState(false)
  const [subMenu, setSubMenu] = useState<SubMenu | null>(null)

  const closeAll = () => {
    setOpen(false)
    setSubMenu(null)
  }

  return (
    <div className={`relative shrink-0 ${collapsed ? 'w-full flex justify-center' : 'w-full'}`}>
      <DropdownMenu open={open} onOpenChange={(next) => { setOpen(next); if (!next) setSubMenu(null) }}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            title="设定"
            aria-label="设定"
            aria-expanded={open}
            className={
              collapsed
                ? 'size-8 min-w-8 min-h-8 rounded-lg text-[color:var(--c-text-faint)] hover:text-[color:var(--c-text-secondary)] flex items-center justify-center'
                : 'w-full justify-start gap-2 px-2.5 py-1.5 text-xs font-medium text-[color:var(--c-text-muted)] rounded-lg'
            }
          >
            <SlidersHorizontal size={collapsed ? 16 : 14} className="shrink-0" aria-hidden />
            {!collapsed && <span className="flex-1 text-left">设定</span>}
            {!collapsed && <ChevronRight size={14} className="shrink-0 opacity-60" aria-hidden />}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="right"
          align="end"
          className={subMenu === 'prose' || subMenu === 'franchise' ? 'w-72 p-3 space-y-3' : 'w-44 p-1'}
        >
          {subMenu === null && (
            <>
              <SubMenuRow
                icon={darkMode ? <Moon size={14} /> : <Sun size={14} />}
                label="主题"
                onClick={() => setSubMenu('theme')}
              />
              <SubMenuRow
                icon={<ALargeSmall size={14} />}
                label="字号"
                onClick={() => setSubMenu('font')}
              />
              <SubMenuRow
                icon={<Sparkles size={14} />}
                label="文风"
                onClick={() => setSubMenu('prose')}
              />
              <SubMenuRow
                icon={<BookMarked size={14} />}
                label="原作出处"
                onClick={() => setSubMenu('franchise')}
              />
            </>
          )}

          {subMenu === 'theme' && (
            <>
              <BackRow onBack={() => setSubMenu(null)} label="主题" />
              <div className="flex flex-col gap-0.5 px-1 py-1" role="listbox" aria-label="颜色主题">
                {THEME_ORDER.map((t) => (
                  <ThemeItem
                    key={t}
                    active={theme === t}
                    label={THEME_LABELS[t]}
                    onClick={() => { setTheme(t); closeAll() }}
                  />
                ))}
              </div>
            </>
          )}

          {subMenu === 'font' && (
            <>
              <BackRow onBack={() => setSubMenu(null)} label="字号" />
              {READING_FONT_SIZE_ORDER.map((s) => (
                <FontSizeItem
                  key={s}
                  active={fontSize === s}
                  label={READING_FONT_SIZE_LABELS[s]}
                  onClick={() => { setFontSize(s); closeAll() }}
                />
              ))}
            </>
          )}

          {subMenu === 'prose' && (
            <>
              <BackRow onBack={() => setSubMenu(null)} label="文风" />
              <ProseStylePanel novelId={novelId} embedded onClose={closeAll} />
            </>
          )}

          {subMenu === 'franchise' && (
            <>
              <BackRow onBack={() => setSubMenu(null)} label="原作出处" />
              <SourceFranchisePanel novelId={novelId} onClose={closeAll} />
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function SubMenuRow({
  icon, label, onClick,
}: { icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={onClick}
      className="flex items-center gap-2 w-full justify-start px-2.5 py-1.5 text-xs text-left text-[color:var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)] rounded-md"
    >
      <span className="shrink-0 text-[color:var(--c-text-faint)]">{icon}</span>
      <span className="flex-1">{label}</span>
      <ChevronRight size={14} className="shrink-0 text-[color:var(--c-text-faint)]" aria-hidden />
    </Button>
  )
}

function BackRow({ onBack, label }: { onBack: () => void; label: string }) {
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={onBack}
      className="flex items-center gap-1.5 w-full justify-start px-2.5 py-1.5 text-xs font-medium text-[color:var(--c-text-muted)] border-b border-[var(--c-border-subtle)] hover:bg-[var(--c-surface-hover)]"
    >
      <ChevronLeft size={14} aria-hidden />
      {label}
    </Button>
  )
}

function ThemeItem({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onClick}
      className={`w-full text-left px-2.5 py-1.5 text-xs rounded-md transition-colors ${
        active
          ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] font-medium'
          : 'text-[color:var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)]'
      }`}
    >
      {label}
    </button>
  )
}

function FontSizeItem({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={onClick}
      className={`w-full justify-start text-left px-2.5 py-1.5 text-xs transition-colors rounded-md ${
        active
          ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] font-medium'
          : 'text-[color:var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)]'
      }`}
    >
      {label}
    </Button>
  )
}
