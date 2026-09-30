import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorMessage } from '../lib/format'
import { api } from './client'
import type { ResolveBody, ReviewStatus } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request
  if (error !== undefined || data === undefined) throw new ApiError(response.status, errorMessage(error))
  return data
}

export const useReviewItems = (status: ReviewStatus) =>
  useQuery({
    queryKey: ['review', status],
    queryFn: () => unwrap(api.GET('/v1/review', { params: { query: { status } } })),
  })

export const useQuotes = () =>
  useQuery({ queryKey: ['quotes'], queryFn: () => unwrap(api.GET('/v1/quotes')) })

export const useQuote = (id: string) =>
  useQuery({
    queryKey: ['quote', id],
    queryFn: () => unwrap(api.GET('/v1/quotes/{quote_request_id}', { params: { path: { quote_request_id: id } } })),
  })

export const useMetrics = () =>
  useQuery({ queryKey: ['metrics'], queryFn: () => unwrap(api.GET('/v1/metrics')) })

export const useGraphStats = () =>
  useQuery({ queryKey: ['graph-stats'], queryFn: () => unwrap(api.GET('/v1/graph/stats')) })

const MIN_SEARCH_LENGTH = 2

export const useGraphSearch = (text: string) =>
  useQuery({
    queryKey: ['graph-search', text],
    queryFn: () => unwrap(api.GET('/v1/graph/search', { params: { query: { q: text } } })),
    enabled: text.trim().length >= MIN_SEARCH_LENGTH,
  })

export const fetchNeighborhood = (nodeId: string) =>
  unwrap(api.GET('/v1/graph/nodes/{node_id}/neighbors', { params: { path: { node_id: nodeId } } }))

export function useResolveReviewItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResolveBody }) =>
      unwrap(
        api.POST('/v1/review/{review_item_id}/resolve', { params: { path: { review_item_id: id } }, body }),
      ),
    onSuccess: async () => {
      await Promise.all(
        ['review', 'quotes', 'quote', 'metrics'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
      )
    },
  })
}

export const fetchSchema = () => unwrap(api.GET('/v1/graph/schema'))

export const fetchLabelNodes = (label: string) =>
  unwrap(api.GET('/v1/graph/nodes', { params: { query: { label } } }))

export const fetchFullGraph = () => unwrap(api.GET('/v1/graph/full'))
