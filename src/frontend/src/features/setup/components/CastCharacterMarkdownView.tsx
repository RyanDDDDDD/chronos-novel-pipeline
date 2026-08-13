import type { CastCharacter, CustomFieldSpec, RelationshipGraph } from '@/shared/types'
import { CharacterMarkdownContent } from '@/shared/components/CharacterMarkdownContent'
import { castPortraitUrl } from '@/features/setup/utils/castPortraitUrl'
import { buildCastCharacterMarkdown } from '@/features/setup/utils/castCharacterMarkdown'

export { CharacterMarkdownContent as CastCharacterMarkdownContent } from '@/shared/components/CharacterMarkdownContent'

export default function CastCharacterMarkdownView({
  character,
  customFieldSpecs,
  relationshipGraph,
}: {
  character: CastCharacter
  customFieldSpecs: CustomFieldSpec[]
  relationshipGraph?: RelationshipGraph
}) {
  const portraitUrl = castPortraitUrl(character.name, character.portrait_path)
  const markdown = buildCastCharacterMarkdown(character, {
    customFieldSpecs,
    relationshipGraph,
    portraitUrl,
  })

  return <CharacterMarkdownContent content={markdown} />
}
