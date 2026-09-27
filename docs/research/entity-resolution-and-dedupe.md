# Entity Resolution and Dedupe

Researched 2026-09-27, feeding ADR designs and the dedupe-agent portion of the architecture.

## Reversible merges, not deletes

**HASH, "Entity Resolution"**
https://hash.ai/glossary/entity-resolution

- Records the diff and merge history so resolution decisions "remain transparent and reversible."
- Bitemporal versioning: can review timing, reasoning, and exact changes made when combining records.
- Directly supports the design choice: `DUPLICATE_OF` / `REVISION_OF` as graph edges, never a destructive merge.

## Blocking strategy (avoid O(n^2) comparison)

**Apify, "Entity Resolution Engine"**
https://apify.com/that_red_bird/entity-resolver

- Records grouped by cheap keys first: email, email domain, phone suffix, company prefix, surname Soundex, name initial. Only compared within a group.
- Oversized blocks (e.g. everyone sharing `gmail.com`) are explicitly skipped rather than compared, to avoid comparison blowup. The run reports how many comparisons this avoided.
- Multiple blocking keys used together so "one bad field can't hide a true match": a skipped gmail.com match can still be caught via phone, name, or company overlap.

## Academic grounding

**"A Survey of Blocking and Filtering Techniques for Entity Resolution"**
https://arxiv.org/pdf/1905.06167

Found via search, not read in full this session. Canonical reference for blocking/filtering technique taxonomy; cite if asked to justify the blocking approach academically.

## Similarity metrics

- Jaccard similarity: set-based, works well for addresses/company names/product titles, matches the "line_key_overlap" Jaccard term used in the dedupe classifier weighting.
- MinHash / LSH: fast approximation of Jaccard for large-scale blocking, not needed at this POC's scale (100-150 customers) but worth knowing for the "how would this scale" interview question.
- Jaccard alone misses latent semantic similarity: pure string/set overlap won't catch a reworded request; that's why the fingerprint design pairs it with account/graph-link and address similarity rather than relying on it alone.

## Not yet found

No direct case study located this session on distributor-specific quote dedupe (duplicate RFQ across branches) beyond the Orbweaver piece already in `README.md` Sources. If this needs strengthening later, search specifically for "RFQ deduplication case study distribution" rather than generic entity resolution.
