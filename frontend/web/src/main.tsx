import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import { App } from './App'
import './shell.css'
import '@phosphor-icons/web/regular'
import 'simple-icons-font/font/simple-icons.css'

registerSW({ immediate: true })
createRoot(document.getElementById('root')!).render(<App />)
