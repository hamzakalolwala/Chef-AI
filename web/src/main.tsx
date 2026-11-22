import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

// No <StrictMode>: its double-mount fights drei's <Html> portals (React 19), dropping labels.
createRoot(document.getElementById('root')!).render(<App />)
