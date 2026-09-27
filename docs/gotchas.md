# Gotchas

## 2026-09-27

- `WebFetch` returns HTTP 403 on Medium article URLs. Medium blocks bot fetches outright, even for public posts. If you need the content, get it from a local export/markdown copy instead of trying to fetch the live URL.
- `WebFetch` returns HTTP 429 on LinkedIn profile URLs. LinkedIn blocks scraping regardless of the tool. Don't burn a call trying; ask the user directly for the background info instead.
- The TigerGraph blog post ("GraphRAG vs Vector RAG: Which Retrieval Approach Wins for Enterprise AI") is often cited alongside the "86% vs 32% multi-hop accuracy" GraphRAG stat, but it contains no benchmark numbers at all: purely qualitative architecture comparison. Verify a stat's actual source before reusing a citation list; don't assume adjacency in a sources section means the number lives in that link.
- A chained Bash command (`git init && mkdir ...`) that gets interrupted mid-execution can leave the first command's effect rolled back rather than partially applied. `git init` reported "Initialized empty Git repository" but the `.git` directory did not exist afterward. Always re-check state (`git status`) after an interrupted command rather than trusting the last printed output.
