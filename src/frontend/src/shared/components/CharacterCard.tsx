import type { CharacterArchive, RelationshipGraph } from '@/shared/types'
import { CharacterMarkdownContent } from '@/shared/components/CharacterMarkdownContent'
import { buildCharacterArchiveMarkdown } from '@/shared/utils/characterArchiveMarkdown'
import { castPortraitUrl } from '@/features/setup/utils/castPortraitUrl'
import { Button } from '@/shared/components/ui/button'

interface Props {
  character: CharacterArchive
  isOpen: boolean
  onToggle: () => void
  relationshipGraph?: RelationshipGraph
  /** Field keys (see profileOverlay.ts::computeFieldKeys) to render with a temporary "just
   * changed" highlight -- sandbox-only; omitted everywhere else. */
  highlightedFields?: Set<string>
  /** Whether this character currently has a portrait. CharacterArchive doesn't carry
   * portrait_path itself -- that's a live lore/cast attribute, not a per-chapter derived
   * snapshot field -- so callers cross-reference the cast roster by name and pass this down. */
  hasPortrait?: boolean
}

export default function CharacterCard({
  character, isOpen, onToggle, relationshipGraph, highlightedFields, hasPortrait = false,
}: Props) {
  const markdown = buildCharacterArchiveMarkdown(character, relationshipGraph)
  // 'x' is a constant placeholder, not the real portrait_path (CharacterArchive doesn't carry
  // it -- see the hasPortrait doc above). The file itself still resolves server-side by
  // character name either way; the only cost of the constant is that this call site won't
  // cache-bust if a portrait is regenerated while it's mounted -- acceptable since there's no
  // regenerate action wired up here.
  const portraitUrl = hasPortrait ? castPortraitUrl(character.name, 'x') : null

  return (
    <section className="border border-slate-200 rounded-lg bg-white overflow-hidden">
      <Button
        type="button"
        variant="ghost"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="w-full justify-start gap-2 px-3.5 py-3 hover:bg-[var(--c-surface-hover)]"
      >
        <span
          className={`text-slate-400 text-xs transition-transform duration-200 shrink-0 ${isOpen ? 'rotate-90' : ''}`}
          aria-hidden
        >
          ▶
        </span>
        {portraitUrl && (
          <img src={portraitUrl} alt="" className="h-10 w-10 shrink-0 rounded-md object-cover" />
        )}
        <div className="min-w-0 flex-1 flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-800 shrink-0">{character.name}</span>
          {character.role && (
            <span className="px-2 py-0.5 rounded-full bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)] text-xs font-medium truncate min-w-0">
              {character.role}
            </span>
          )}
        </div>
      </Button>
      {isOpen && (
        <div className="border-t border-slate-100 px-3.5 pb-3.5 pt-2 text-sm text-[var(--c-text-secondary)]">
          <CharacterMarkdownContent content={markdown} highlightedFields={highlightedFields} />
        </div>
      )}
    </section>
  )
}
