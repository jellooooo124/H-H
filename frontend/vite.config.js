import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'
export default defineConfig({
  plugins:[vue()],
  build:{rollupOptions:{input:{clinician:resolve(import.meta.dirname,'index.html'),patient:resolve(import.meta.dirname,'patient.html')}}},
  server:{proxy:{'/v1':'http://127.0.0.1:8000','/v2':'http://127.0.0.1:8000','/v3':'http://127.0.0.1:8000','/v4':'http://127.0.0.1:8000','/health':'http://127.0.0.1:8000'}}
})
