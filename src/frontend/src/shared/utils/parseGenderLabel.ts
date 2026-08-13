import { GENDER_LABELS } from '@/shared/utils/characterFieldLabels'

/** Reverse of formatGenderLabel for markdown meta parsing. */
export function parseGenderLabel(label: string): string {
  const trimmed = label.trim()
  for (const [key, value] of Object.entries(GENDER_LABELS)) {
    if (value === trimmed) return key
  }
  return trimmed
}
