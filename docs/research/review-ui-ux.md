# Review UI and UX: human-in-the-loop, tables, confidence display, antd theming

Researched 2026-09-30 to guide a polish pass on the reviewer web app (`frontend/`). Each finding is marked verified (source page fetched directly) or search-only (seen in a search result summary, not fetched).

## Human-in-the-loop review queues

Verified, maviklabs.com/blog/human-in-the-loop-review-queue-2026:

- Each queue item should state why it needs review ("clear trigger reason"), the proposed action with its confidence, and an evidence snapshot taken at review time.
- Approve and reject should be single-click; reviewer friction is the main cost.
- Keep the escalation rate low so reviewers look only at genuinely ambiguous cases (their target: 10 to 15 percent).

Search-only (velt.dev, aufaitux.com, parseur.com): reviewers decide faster and with fewer errors when the reasoning, source references and the flagged gap sit next to the output; a good handoff says "why it needs review" and "what will happen next".

Applied here: the review item's `fact` is the trigger reason and leads each card; evidence sits directly under it; Approve and Correct stay one click; a resolved or auto-sent state says what happens next.

## Showing model confidence

Search-only (eleken.co, aiuxdesign.guide, cocreate.consulting, arxiv 2410.21183):

- Put a plain-language confidence label next to the output, not only a number.
- Use color bands for confidence (one source: amber for medium, red for low) so the eye goes to low scores first.
- Below the threshold, present the result as a verification card that needs an explicit confirm.

Applied here: judge dimension scores are colored in three bands (strong, borderline, weak) and overall confidence is shown as a percent next to a plain Auto-send or Needs review label. The bands are visual only: the real trust decision uses the calibrated threshold (`current_threshold` in `backend/app/judge/service.py`), so the UI does not print a threshold number that could drift from it.

## Data tables

Verified, pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables:

- Left-align text, right-align quantitative numbers, and align each header with its column content. Never center.
- Make the whole row clickable when details live elsewhere.
- Prefer subtle row dividers over zebra stripes.

Search-only (uxpatterns.dev, setproduct.com): use tabular (fixed-width) digits in number columns; status strings should become color-coded badges; "no data yet" and "filter matched nothing" are different empty states with different copy.

Applied here: money, quantity and percent columns are right-aligned with `tabular-nums`; queue and quote rows open the quote on click; raw status strings (`needs_review`, `DUPLICATE_OF`, `identical_sku_set`, `required_fields`) are mapped to human labels.

## Ant Design 6 theming

Verified, ant.design/docs/react/customize-theme:

- Global tokens go in `<ConfigProvider theme={{ token: { colorPrimary, borderRadius, fontFamily } }}>`; per-component tokens under `theme.components.<Name>`.
- `theme.darkAlgorithm` and `theme.compactAlgorithm` exist and can be combined.

Not verified: the fetched summary said CSS variables are off by default in v6; that contradicts other v6 material and was not relied on.

## LLM text containing markdown

No source needed a search: model output (judge rationale, facts, agent adjustment detail) can contain inline markdown such as `**bold**` or backticks, which shows as raw asterisks when rendered as plain text. The fix used is to render those fields through `react-markdown` restricted to inline elements, so formatting shows as formatting and no HTML from the model is ever injected.
