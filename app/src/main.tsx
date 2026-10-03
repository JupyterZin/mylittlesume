import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import '@fontsource-variable/archivo/wdth.css'
import './styles/tokens.css'
import './styles/app.css'
import App from './App'

const PoseRender = lazy(() => import('./render/PoseRender'))
const renderPose = new URLSearchParams(location.search).has('render-pose')

if (!renderPose && 'serviceWorker' in navigator) {
  registerSW({ immediate: true })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {renderPose ? (
      <Suspense fallback={null}>
        <PoseRender />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
)
