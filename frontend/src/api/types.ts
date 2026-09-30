import type { components } from './schema'

type Schemas = components['schemas']

export type ReviewItem = Schemas['ReviewItemListResponse']
export type QuoteSummary = Schemas['QuoteSummaryResponse']
export type QuoteDetail = Schemas['QuoteDetailResponse']
export type QuoteEstimate = Schemas['QuoteEstimateResponse']
export type QuoteReviewItem = Schemas['QuoteReviewItemResponse']
export type QuoteJudgeVerdict = Schemas['QuoteJudgeVerdictResponse']
export type QuoteSkuInfo = Schemas['QuoteSkuInfoResponse']
export type DedupeVerdict = Schemas['QuoteDedupeVerdictResponse']
export type Metrics = Schemas['MetricsResponse']
export type ResolveBody = Schemas['ResolveReviewItemRequest']
export type DraftLine = NonNullable<QuoteEstimate['draft']>['lines'][number]

export type ReviewStatus = 'open' | 'resolved' | 'all'

export type GraphNode = Schemas['GraphNode']
export type GraphEdge = Schemas['GraphEdge']
export type Neighborhood = Schemas['NeighborhoodResponse']
export type GraphStats = Schemas['GraphStatsResponse']
export type SchemaOverview = Schemas['SchemaOverviewResponse']
export type LabelNodes = Schemas['LabelNodesResponse']
export type FullGraph = Schemas['FullGraphResponse']
