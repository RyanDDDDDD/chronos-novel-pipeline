import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { applyTheme, resolveInitialTheme } from '@/shared/utils/theme'
import { applyReadingFontSize, resolveInitialReadingFontSize } from '@/shared/utils/readingFontSize'
import '@/index.css'
import App from '@/App'
import { queryClient } from '@/shared/lib/queryClient'
import { store } from '@/shared/store/store'
import { useNovels } from '@/shared/queries/novels'

/** Root path: parse the backend active novel and redirect to its pipeline page; if the novels are not loaded, they will be rendered empty.*/
function RootRedirect() {
  const { data: novels = [] } = useNovels()
  const active = novels.find((n) => n.active)?.id ?? novels[0]?.id
  if (!active) return null
  return <Navigate to={`/novel/${active}/pipeline`} replace />
}

applyTheme(resolveInitialTheme())
applyReadingFontSize(resolveInitialReadingFontSize())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Provider store={store}>
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route path="/" element={<RootRedirect />} />
            <Route path="/novel/:novelId/*" element={<App />} />
          </Routes>
        </QueryClientProvider>
      </BrowserRouter>
    </Provider>
  </StrictMode>,
)
