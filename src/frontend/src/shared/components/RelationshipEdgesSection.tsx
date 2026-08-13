import type { CharacterRelationship } from '@/shared/utils/relationshipEdges'

/** Shared by CharacterCard (per-chapter archive) and CastCharacterCard (base setup card) --
 * both just filter the same fetched-once relationship graph down to this character's edges
 * and hand the list to this component. Read-only: relationship edges are generated in the
 * background when a character is created, not editable from either card. */
export default function RelationshipEdgesSection({
  relationships,
}: {
  relationships: CharacterRelationship[]
}) {
  return (
    <section>
      <div className="text-xs font-medium text-slate-500 mb-1.5">关系</div>
      {relationships.length === 0 ? (
        <p className="text-sm text-slate-400">暂无</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {relationships.map(({ other, direction, edge }, i) => {
            const terms = [...(edge.from_ref_terms ?? []), ...(edge.to_ref_terms ?? [])]
            return (
              <span
                key={`${direction}-${other}-${i}`}
                title={edge.relationship_anchor || undefined}
                className="px-2 py-1 rounded-lg bg-slate-100 text-slate-700 text-xs"
              >
                {direction === 'from' ? '→' : '←'} {other}（{edge.nature}）
                {terms.length > 0 && <span className="text-slate-400">·{terms.join('/')}</span>}
              </span>
            )
          })}
        </div>
      )}
    </section>
  )
}
