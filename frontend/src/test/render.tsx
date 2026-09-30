import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

type Handler = (request: Request) => Response | Promise<Response>

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

/** Replaces fetch, the boundary the API client calls through. Keys are "METHOD /pathname". */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: Request | string | URL) => {
    const request = input instanceof Request ? input : new Request(input)
    const key = `${request.method} ${new URL(request.url).pathname}`
    const handler = routes[key]
    if (!handler) throw new Error(`unmocked request: ${key}`)
    return handler(request)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
