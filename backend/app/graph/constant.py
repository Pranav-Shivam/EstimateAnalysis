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
# A same-customer DISTINCT pair overlapping at least this much is a variant of the earlier request. It sits below the
# classifier's CONTENT_SUPERSET_FLOOR (0.4, which makes revisions) so partial overlap that is not a superset counts.
VARIANT_MIN_JACCARD = 0.2
# A fixed seed makes Leiden deterministic; without it two runs can label communities differently.
LEIDEN_SEED = 42
LEIDEN_GAMMA = 1.0
LOCAL_MAX_HOPS = 2
LOCAL_MAX_NODES = 50
LOCAL_MAX_PATHS = 500
# Hubs appear in a local result only as leaves. Walking through one would return every member of the category or family.
HUB_LABELS = ("PricingCategory", "ProductFamily")
# Postgres advisory locks are keyed by two ints; this fixed first int keeps the rebuild lock apart from any other use.
REBUILD_LOCK_CLASSID = 928374
MAX_EXAMPLE_SKUS = 5
MAX_MEMBER_NAMES = 30
# The explorer returns at most this many neighbors of a node; a hub with more is reported as truncated.
NEIGHBOR_LIMIT = 60
SEARCH_LIMIT = 15
# One label listed in the explorer returns at most this many nodes, most connected first.
LABEL_LIST_LIMIT = 60
