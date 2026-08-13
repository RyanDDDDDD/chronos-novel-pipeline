import type { AppDispatch } from '@/shared/store/store'
import { serviceStatusLoaded, type PingEntry } from '@/shared/store/servicePingSlice'

export interface ServiceStatusResponse {
  llm: PingEntry
  search: PingEntry
}

export async function fetchServiceStatus(dispatch: AppDispatch): Promise<void> {
  try {
    const res = await fetch('/api/health/service-status')
    const body = (await res.json().catch(() => null)) as ServiceStatusResponse | null
    if (res.ok && body?.llm && body?.search) {
      dispatch(serviceStatusLoaded(body))
    }
  } catch {
    /* status icons are informational; a failed fetch leaves the last known state */
  }
}
