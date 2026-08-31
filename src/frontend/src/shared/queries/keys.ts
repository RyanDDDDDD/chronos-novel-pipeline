//Query key SSOT. invalidation can hit all novelId variants with a prefix (such as ['setup','world']).
export const novelsKey = ['novels'] as const
export const setupKey = (kind: 'world' | 'cast' | 'plot' | 'attachments', novelId: string) =>
  ['setup', kind, novelId] as const
export const relationshipGraphKey = (novelId: string) =>
  ['setup', 'relationship-graph', novelId] as const
export const storySandboxHistoryKey = (novelId: string, chapter: number, branchId: string) =>
  ['story-sandbox', 'history', novelId, chapter, branchId] as const
export const storySandboxBranchesKey = (novelId: string, chapter: number) =>
  ['story-sandbox', 'branches', novelId, chapter] as const
export const sandboxCastArchivesKey = (novelId: string, chapter: number, namesJoin: string) =>
  ['sandboxCastArchives', novelId, chapter, namesJoin] as const
export const sandboxRelatedCastArchivesKey = (novelId: string, chapter: number, presentNamesJoin: string) =>
  ['sandboxRelatedCastArchives', novelId, chapter, presentNamesJoin] as const
export const setupSkillsKey = ['setup', 'skills'] as const
export const archivesKey = (novelId: string, chapter?: number) =>
  chapter == null ? (['archives', novelId] as const) : (['archives', novelId, chapter] as const)
export const skeletonKey = (novelId: string, chapter: number) =>
  ['skeleton', novelId, chapter] as const
export const proseStylesKey = ['prose-styles'] as const
export const proseStyleKey = (id: string) => ['prose-style', id] as const
export const sourceFranchiseKey = (id: string) => ['source-franchise', id] as const
export const sandboxDialogueTurnCountKey = (id: string) => ['sandbox-dialogue-turn-count', id] as const
export const proseStylePresetContentKey = (presetId: string) => ['prose-style-preset-content', presetId] as const
export const reviewHookCardKey = (name: string) => ['review-hook-card', name] as const
export const stateDeriveFieldsKey = ['state-derive-fields'] as const
export const chaptersKey = (novelId: string) => ['chapters', novelId] as const
export const manuscriptChaptersKey = (novelId: string) => ['manuscripts', novelId] as const
export const manuscriptKey = (novelId: string, chapter: number) =>
  ['manuscript', novelId, chapter] as const
export const authorLoopDialogueKey = (novelId: string) =>
  ['author-loop', 'dialogue-config', novelId] as const
export const authorLoopReviewKey = ['author-loop', 'review'] as const
export const modelRegistryKey = ['model-registry'] as const
export const imageGenModelRegistryKey = ['image-gen-model-registry'] as const
export const tokenStatsKey = ['token-stats'] as const
export const chronosConfigKey = ['chronos-config'] as const
export const sandboxMemoryArchiveKey = (novelId: string, chapter: number, branchId: string) =>
  ['sandbox-memory-archive', novelId, chapter, branchId] as const
export const novitaModelCatalogKey = ['novita-model-catalog'] as const
export const artStylePresetsKey = ['art-style-presets'] as const
// Prefix-only key so the WS listener can invalidate every novelId/chapter variant at once.
export const authorSceneImagesPrefixKey = ['author', 'scene-images'] as const
export const authorSceneImagesKey = (novelId: string, chapter: number) =>
  [...authorSceneImagesPrefixKey, novelId, chapter] as const
