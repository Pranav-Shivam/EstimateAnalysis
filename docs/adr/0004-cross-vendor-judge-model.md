# ADR-0004: Use a different-vendor model (Claude Haiku) as the eval judge, not the same vendor as the agent

## Status
Proposed

## Context
The reference architecture requires an LLM-as-judge to score every agent-produced estimate before it reaches a human or customer. The source article calls out a specific known failure mode: "same-model judging tends to share the same blind spots." The developer's only existing API key at the time of this decision was OpenAI's ("Which API keys do you already have vs need to get?" answered "OpenAI (GPT)"), which is also the intended provider for the main agent (GPT-4o).

## Decision Drivers
- Avoiding correlated blind spots between the agent and its judge, per the article's explicit finding.
- Acceptable added cost: a small one-time/ongoing spend (~$5) was explicitly approved by the developer over the free local-model alternative.
- Stronger interview narrative: a cross-vendor judge ("different vendor, not just different checkpoint") is a more credible eval-design story than a same-vendor judge or a purely cost-driven local model.

## Decision
Use OpenAI GPT-4o as the agent model and Anthropic Claude Haiku as the judge model: two different model vendors/families, not two checkpoints of the same family.

## Alternatives Considered
- **Same-vendor judge (e.g. GPT-4o-mini judging GPT-4o)**: cheaper and requires no second API key, but directly contradicts the article's finding that same-model judging shares blind spots; rejected on that basis.
- **Local Ollama model as judge (e.g. Qwen2.5 7B on the developer's RTX 4060)**: free, and satisfies the "different family" requirement at zero marginal cost, but judge quality is weaker than a frontier model; rejected in favor of paying for Anthropic's Haiku given the small (~$5) cost was acceptable.

## Consequences
- **Positive**: cross-vendor judge meaningfully reduces the risk of the judge sharing the agent's specific reasoning failures; stronger, more defensible interview talking point on eval design.
- **Negative / accepted trade-offs**: requires managing and billing two separate LLM provider accounts instead of one; small added ongoing cost versus an all-OpenAI or all-local setup.

## Notes
Decided during stack-selection discussion, directly citing the source article's same-model-judge blind-spot finding. Carried into `README.md` tech stack table (Agent LLM: OpenAI GPT-4o; Judge LLM: Anthropic Claude Haiku).
