import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Tauri erwartet den Entwicklungsserver auf einem festen Port.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
  build: { target: 'es2022' },
})
