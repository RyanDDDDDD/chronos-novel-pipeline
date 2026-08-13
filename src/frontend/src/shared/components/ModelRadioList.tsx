import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/shared/components/ui/input-group'
import { RadioGroup, RadioGroupItem } from '@/shared/components/ui/radio-group'

interface Props {
  models: string[]
  name: string
  selected: string | undefined
  onSelect: (id: string) => void
  searchPlaceholder?: string
  onSearchMiss?: () => void
}

function ModelRadioListInner({
  models, name, selected, onSelect, searchPlaceholder = '搜索模型…', onSearchMiss,
}: Props) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return models
    return models.filter(id => id.toLowerCase().includes(needle))
  }, [models, query])

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!onSearchMiss) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.trim().length === 0 || filtered.length > 0) return
    debounceRef.current = setTimeout(() => onSearchMiss(), 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, filtered.length, onSearchMiss])

  if (models.length === 0) return null

  const searching = query.trim().length > 0
  return (
    <div className="space-y-1">
      <InputGroup className="w-full">
        <InputGroupInput
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label="搜索模型"
          className="font-mono text-xs"
        />
        <InputGroupAddon>
          <Search />
        </InputGroupAddon>
      </InputGroup>
      <div className="text-[11px] text-[var(--c-text-muted)]">
        {searching
          ? `显示 ${filtered.length} / ${models.length} 个模型`
          : `共 ${models.length} 个模型${models.length > 6 ? '，列表内滚动选择' : ''}`}
      </div>
      <RadioGroup
        value={selected}
        onValueChange={onSelect}
        aria-label={name}
        className="max-h-60 overflow-y-auto space-y-2 rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] p-1"
      >
        {filtered.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-[var(--c-text-muted)]">无匹配模型</div>
        ) : (
          filtered.map(id => (
            <label
              key={id}
              className={`flex items-center gap-2 border rounded-md px-3 py-2 cursor-pointer text-xs ${
                selected === id ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]' : 'border-[var(--c-border)]'
              }`}
            >
              <RadioGroupItem value={id} />
              <span className="font-mono break-all">{id}</span>
            </label>
          ))
        )}
      </RadioGroup>
    </div>
  )
}

export default function ModelRadioList(props: Props) {
  return <ModelRadioListInner key={props.models.join('\0')} {...props} />
}
