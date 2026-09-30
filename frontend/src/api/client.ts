import createClient from 'openapi-fetch'
import type { paths } from './schema'

// fetch is looked up per call, not captured at import, so tests can replace globalThis.fetch.
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL ?? 'http://localhost:7060',
  fetch: (request) => globalThis.fetch(request),
})
