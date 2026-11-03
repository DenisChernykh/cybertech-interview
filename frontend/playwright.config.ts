import { defineConfig } from '@playwright/test'
export default defineConfig({ testDir: './tests', workers: 1, timeout: 30000, use: { baseURL: process.env.BASE_URL || 'http://localhost:5179', screenshot: 'only-on-failure', trace: 'retain-on-failure' } })
