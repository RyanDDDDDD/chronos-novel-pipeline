/** Display labels for character archive / profile_mutate field keys (aligned with CharacterCard sections). */
export const CHARACTER_PROFILE_FIELD_LABELS: Record<string, string> = {
  identity_background: '身份背景',
  personality: '性格',
  race: '种族',
  hobbies: '爱好',
  verbal_tic: '口癖',
  gender: '性别',
  sliders: '成长轴',
  physique: '体格',
  location: '地点',
  role: '角色类型',
  relationship_to_lead: '与主角关系',
}

export const GENDER_LABELS: Record<string, string> = {
  female: '女',
  male: '男',
}

export function characterProfileFieldLabel(key: string): string {
  return CHARACTER_PROFILE_FIELD_LABELS[key] ?? key
}

export function formatGenderLabel(value: string): string {
  return GENDER_LABELS[value] ?? value
}

/** Scalar profile_mutate / archive field value for UI (e.g. gender enum → 中文). */
export function formatProfileScalarDisplay(fieldKey: string, value: unknown): string {
  if (fieldKey === 'gender' && typeof value === 'string') return formatGenderLabel(value)
  return String(value)
}
