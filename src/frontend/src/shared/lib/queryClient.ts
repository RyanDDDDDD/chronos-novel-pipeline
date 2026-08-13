import { QueryClient } from '@tanstack/react-query'

//Local development tools: Focus retrieval is noise, so turn off refetchOnWindowFocus; the per-novel content rarely changes except build/delete files, giving 30s staleTime.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
})
