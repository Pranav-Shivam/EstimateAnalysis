from datetime import date

# The synthetic contracts span 2023 to 2027 and only 9 of 125 are active on the real current date, which would
# make every discount look expired and hide the category-mismatch guardrail. At this date 117 of 125 are active.
# A real system would use the request's received timestamp instead.
DATASET_AS_OF = date(2024, 9, 1)

MAX_GUARDRAIL_RETRIES = 3
MAX_AGENT_STEPS = 12
# Each agent turn costs a few graph supersteps, so the library default of 25 would trip before MAX_AGENT_STEPS.
RECURSION_LIMIT = 100
