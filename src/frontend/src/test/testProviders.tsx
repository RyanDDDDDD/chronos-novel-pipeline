import React from 'react'
import { TooltipProvider } from '@/shared/components/ui/tooltip'

/** Shared test wrapper: TooltipProvider for truncated-text tooltips. Sonner is mounted per-test where toast assertions are needed. */
export function TestProviders({ children }: { children: React.ReactNode }) {
  return <TooltipProvider>{children}</TooltipProvider>
}
