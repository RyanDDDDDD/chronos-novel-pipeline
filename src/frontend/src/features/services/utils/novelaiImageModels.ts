// NovelAI Diffusion model ids accepted by POST /ai/generate-image (the `model` field).
// nai-diffusion-5-full / -curated verified working on a Tablet-tier account 2026-08-28.
export const NOVELAI_IMAGE_MODELS: { id: string; label: string }[] = [
  { id: 'nai-diffusion-5-full', label: 'NAI Diffusion V5 Full' },
  { id: 'nai-diffusion-5-curated', label: 'NAI Diffusion V5 Curated' },
  { id: 'nai-diffusion-4-5-full', label: 'NAI Diffusion V4.5 Full' },
  { id: 'nai-diffusion-4-5-curated', label: 'NAI Diffusion V4.5 Curated' },
]

export const DEFAULT_NOVELAI_IMAGE_MODEL = 'nai-diffusion-5-full'
