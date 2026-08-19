import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Bind IPv4 loopback explicitly. The default only listened on [::1],
    // so browsers that resolve localhost to 127.0.0.1 got
    // ERR_CONNECTION_REFUSED.
    host: '127.0.0.1',
    port: 5173,
  },
})