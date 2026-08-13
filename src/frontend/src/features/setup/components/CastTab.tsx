import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Search, Users } from 'lucide-react'
import EmptyStateCard from '@/shared/components/EmptyStateCard'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/shared/components/ui/input-group'
import { useCast, useCustomFields, useRelationshipGraph } from '@/shared/queries/setup'
import { deleteCastCharacter, patchCastCharacter } from '@/shared/utils/setup'
import { filterCharactersByName } from '@/shared/utils/filterCharactersByName'
import CastCharacterGridCard from '@/features/setup/components/CastCharacterGridCard'
import CastCharacterDetailModal from '@/features/setup/components/CastCharacterDetailModal'

export default function CastTab() {
  const queryClient = useQueryClient()
  const { data: chars = [] } = useCast()
  const { data: relationshipGraph } = useRelationshipGraph()
  const { data: customFieldSpecs = [] } = useCustomFields()
  const [query, setQuery] = useState('')
  const [selectedName, setSelectedName] = useState<string | null>(null)

  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ['setup', 'cast'] })
  }, [queryClient])

  const filtered = useMemo(() => filterCharactersByName(chars, query), [chars, query])
  const searching = query.trim().length > 0
  const selectedCharacter = selectedName
    ? chars.find((c) => c.name === selectedName) ?? null
    : null

  useEffect(() => {
    if (selectedName && !chars.some((c) => c.name === selectedName)) {
      setSelectedName(null)
    }
  }, [chars, selectedName])

  const handleSave = async (name: string, fields: Parameters<typeof patchCastCharacter>[1]) => {
    const res = await patchCastCharacter(name, fields)
    if (res.ok) void queryClient.invalidateQueries({ queryKey: ['setup', 'cast'] })
    return res
  }

  const handleDelete = async (name: string) => {
    const res = await deleteCastCharacter(name)
    if (res.ok) void queryClient.invalidateQueries({ queryKey: ['setup', 'cast'] })
    return res
  }

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      {chars.length === 0 && (
        <EmptyStateCard icon={Users} message="尚未生成人物，去「对话」页让共创者构建。" />
      )}
      {chars.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-xs text-[var(--c-text-muted)] tabular-nums shrink-0">
              {searching
                ? `共 ${chars.length} 人 · 匹配 ${filtered.length}`
                : `共 ${chars.length} 人`}
            </div>
            <InputGroup className="w-44">
              <InputGroupInput
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索角色名"
                aria-label="搜索角色名"
                className="text-sm"
              />
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
            </InputGroup>
          </div>
          {searching && filtered.length === 0 ? (
            <p className="text-sm text-[var(--c-text-muted)]">未找到匹配角色</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {filtered.map((character) => (
                <CastCharacterGridCard
                  key={character.name}
                  character={character}
                  onOpen={() => setSelectedName(character.name)}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </div>
      )}

      <CastCharacterDetailModal
        character={selectedCharacter}
        open={selectedName != null}
        onOpenChange={(next) => {
          if (!next) setSelectedName(null)
        }}
        relationshipGraph={relationshipGraph}
        customFieldSpecs={customFieldSpecs}
        onSave={handleSave}
      />
    </div>
  )
}
