# A consolidation job that hits a dropped connection or a deadlock is retried with backoff (2, 4, 8, 16 seconds)
# rather than lost. Anything else (a missing row, a bad dimension) is a bug a retry cannot fix, so it fails at once.
CONSOLIDATION_MAX_ATTEMPTS = 5
CONSOLIDATION_RETRY_EXPONENTIAL_WAIT = 2
