# Source article graph schema (10 node types, 15 edge types)

Provided by the project owner on 2026-09-28 during Phase 4 brainstorming. This is the reference the roadmap means by "the article's fuller schema". Phase 4's spec records which subset is built and why.

## Nodes

| # | Node | Represents |
|---|---|---|
| 1 | Customer | The business/account placing the RFQ |
| 2 | Person | Individual contacts |
| 3 | Contract | Customer-specific commercial terms |
| 4 | PricingCategory | Pricing/discount categories |
| 5 | ProductFamily | A logical family/group of products |
| 6 | SKU | The concrete sellable item |
| 7 | Project | The customer's job/project |
| 8 | Site | Physical location where the project happens |
| 9 | QuoteRequest | The incoming RFQ |
| 10 | Quote | The generated/approved quotation |

## Edges

| # | Edge | Meaning |
|---|---|---|
| 1 | WORKS_FOR | Person to Customer |
| 2 | HOLDS | Customer to Contract |
| 3 | COVERS | Contract to PricingCategory |
| 4 | IN_FAMILY | SKU to ProductFamily |
| 5 | REPLACED_BY | SKU to replacement SKU |
| 6 | PRICED_IN | SKU to PricingCategory |
| 7 | REQUIRES | SKU to required accessory SKU |
| 8 | HAS_PROJECT | Customer to Project |
| 9 | AT_SITE | Project to Site |
| 10 | FOR_PROJECT | QuoteRequest to Project |
| 11 | DUPLICATE_OF | QuoteRequest to another QuoteRequest |
| 12 | REVISION_OF | QuoteRequest to earlier QuoteRequest |
| 13 | VARIANT_OF | QuoteRequest to related variant |
| 14 | SUPERSEDES | A newer record supersedes an older one |
| 15 | PRICE_VARIANCE | A pricing difference/adjustment |

## Reasoning paths the article names

- Customer HOLDS Contract, Contract COVERS PricingCategory, SKU PRICED_IN PricingCategory (discount applicability).
- SKU REPLACED_BY SKU (discontinued swap).
- SKU REQUIRES SKU (missing required part).
- Person WORKS_FOR Customer, Customer HAS_PROJECT Project, Project AT_SITE Site (dedupe).
- QuoteRequest DUPLICATE_OF {score} QuoteRequest (dedupe result carries a similarity score).

## Coverage against the synthetic data as of Phase 3

| Article element | In current data? |
|---|---|
| Customer, Contract, PricingCategory, SKU | Yes (Postgres) |
| Site | Yes (194 rows, hangs directly off Customer) |
| Person | In `customers.json` only (236 contacts); not loaded into Postgres |
| QuoteRequest | Yes (`quote_requests`) |
| Quote | Partly (`estimate_drafts`) |
| ProductFamily, IN_FAMILY | No (catalog has no family field) |
| Project, HAS_PROJECT, FOR_PROJECT | No (no project entity generated) |
| DUPLICATE_OF, REVISION_OF | Yes (`dedupe_verdicts`, with Jaccard scores) |
| VARIANT_OF, SUPERSEDES, PRICE_VARIANCE | No defined source |
