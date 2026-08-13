import type { CastCharacter } from '@/shared/types'
import { formatGenderLabel } from '@/shared/utils/characterFieldLabels'

export function castDisplayName(character: CastCharacter): string {
  return character.given_name && character.given_name !== character.name
    ? `${character.name}（${character.given_name}）`
    : character.name
}

export function CastCharacterTags({ character }: { character: CastCharacter }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {character.role && (
        <span className="px-2 py-0.5 rounded-full bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)] text-xs font-medium">
          {character.role}
        </span>
      )}
      {character.gender && (
        <span className="px-2 py-0.5 rounded-full bg-[var(--c-surface-muted)] text-[var(--c-text-secondary)] text-xs">
          {formatGenderLabel(character.gender)}
        </span>
      )}
      {character.race && (
        <span className="px-2 py-0.5 rounded-full bg-[var(--c-surface-muted)] text-[var(--c-text-secondary)] text-xs">
          {character.race}
        </span>
      )}
    </div>
  )
}
