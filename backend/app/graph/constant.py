NODE_LABELS = (
    "Customer", "Person", "Contract", "PricingCategory", "ProductFamily", "SKU", "Project", "Site",
    "QuoteRequest", "Quote", "GraphMeta",
)
EDGE_TYPES = (
    "WORKS_FOR", "HOLDS", "COVERS", "IN_FAMILY", "REPLACED_BY", "PRICED_IN", "REQUIRES", "HAS_PROJECT", "AT_SITE",
    "FOR_PROJECT", "DUPLICATE_OF", "REVISION_OF", "VARIANT_OF", "SUPERSEDES", "PRICE_VARIANCE",
)
BATCH_SIZE = 1000
# A REPLACED_BY chain longer than this is treated as unresolvable: the run ends for review instead of walking on.
MAX_CHAIN_HOPS = 10
