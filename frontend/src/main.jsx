import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './index.css'

const isDev = import.meta.env.DEV
const root = createRoot(document.getElementById('root'))

// In dev, avoid StrictMode double-mount to prevent noisy WS connect/disconnect churn.
if (isDev) {
  root.render(<App />)
} else {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>
  )
}
