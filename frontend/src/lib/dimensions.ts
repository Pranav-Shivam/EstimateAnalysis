const LABELS: Record<string, string> = {
  price_provenance: 'Price source',
  contract_discount: 'Contract discount',
  graph_completion: 'Graph completeness',
  guardrail: 'Guardrail',
}

export function dimensionLabel(dimension: string): string {
  return LABELS[dimension] ?? dimension
}
