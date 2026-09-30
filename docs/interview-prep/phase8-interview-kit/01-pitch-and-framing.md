# 01. Pitch and Framing

Written for me to say out loud. Short sentences on purpose.

## The boundary rule

Read this before every interview.

- This project is a personal rebuild on synthetic data. It is not the system I work on at my day job.
- I never present it as the work project.
- I never mix outcomes. Anything measured at work stays at work and is not quoted here. Anything measured in this POC (test counts, calibration results) is described as POC results on synthetic data.
- If asked "did this run in production", the answer is "no, this one is a proof of concept on generated data".
- If asked about work details, I say I cannot share code, data, or numbers from work, and I bring the conversation back to what I built and learned here.

## The framing script

Say these four beats in this order. It takes about 40 seconds.

**(a) The day job.** "In my day job I work on a production system of this kind. It takes messy quote requests and turns them into priced estimates. I can't share that code or its data."

**(b) The rebuild.** "So I rebuilt the architecture from scratch as a personal project, on synthetic data. Same problem shape, but everything in it is generated and public, so I can show every part."

**(c) The addition.** "I used the rebuild to add something I wanted to understand deeply: an eval and calibration layer. That means a judge model, a hand-labeled golden set, and a confidence threshold I derived from data instead of copying a number."

**(d) The lessons.** "Here is what the rebuild taught me." Then go into the pitch, or into one lesson from below.

## The 90-second pitch

> A B2B distributor gets quote requests as messy emails. A skilled rep spends thirty to forty-five minutes turning one into a priced quote. And a lot of what makes the quote correct lives in people's heads. Which part is discontinued. Which part needs an accessory. Which discount applies to which category.
>
> I built an agent that reads the email and prices it. But the interesting part is not the agent. It is everything around it.
>
> First, hard rules are plain code, not another model. A discount is only allowed if the customer's contract covers that category. The model can propose a number. The code decides. And those checks are anchored on facts the model did not write, like the customer on the stored request.
>
> Second, a knowledge graph answers the questions text search cannot. What replaces a discontinued part, and what does the replacement require. It is rebuilt from Postgres, so Postgres stays the source of truth.
>
> Third, a judge from a different model vendor scores every draft, and a draft below a calibrated threshold goes to a human with one specific fact to check, not the whole quote.
>
> Fourth, when a human corrects that fact, it becomes a permanent price, requirement, or contract edge. The next identical quote does not get flagged.
>
> It runs on synthetic data, so I am careful about what it proves. It proves the design and the plumbing. I also ran the real GPT-4o agent over 40 test emails once, for about a dollar. The agent did well. The intake step in front of it was weaker than I expected, and that is my next fix.

That is about 250 words, which is roughly 90 seconds at a relaxed pace.

## The 5-minute pitch

Use this when the interviewer says "walk me through it". Pause at each heading. Let them interrupt.

### The problem (30 seconds)

> Quote requests come in as free-text email. No part numbers. Sent by whoever is on site that day. Turning one into a correct quote is slow and error-prone. The mistakes are of four kinds. A discontinued part gets substituted wrongly. A required part gets left off. A discount gets applied to a category the contract does not cover. Or the same job arrives twice and gets two different prices. And when a rep fixes a mistake, the fix stays in that one quote.

### Why synthetic data (20 seconds)

> There is no real dataset for this project. So I generated one that is structurally realistic. Around 650 parts, 125 customers, contracts that cover some categories at a discount, discontinued parts that point at replacements, parts that require other parts. And 60 test emails, each hiding one planted situation, with the answer key stored separately. That gave every later piece something real to reason over and something to be measured against.

### The pipeline (90 seconds)

> An email comes in and goes through intake. One model call turns it into a typed object. Then code, not the model, matches the names to real customer and part records. If it cannot match with confidence, it leaves the field empty instead of guessing.
>
> Next is dedupe. It compares the new request to earlier ones from the same customer, site, or contract. If the set of parts is identical, it is a duplicate. If it is the earlier set plus more, it is a revision. Otherwise it is distinct.
>
> Then the agent loop, in LangGraph. GPT-4o calls tools: look up the customer, search the price book, walk the graph for replacements and required parts, check contract coverage, predict a price if there is none. It submits a draft. Guardrails run. If they fail, the agent gets the exact complaints and retries, up to three times. If it still fails, the draft goes to review. It never goes out.
>
> Then the judge. Claude Haiku scores three things, using evidence that code assembled: how well supported each price is, how solid each discount is, and whether the graph shows a discontinued or missing part. The overall score is the lowest of the three, so one weak fact cannot hide behind two strong ones.

### The eval layer, which is my addition (90 seconds)

> This is the part I most wanted to understand. The article I started from uses a 0.85 confidence cutoff. I did not want to copy a number. So I hand-labeled 32 cases, 15 to trust and 17 to escalate. I swept every score the judge produced as a candidate threshold and picked the lowest one where agreement with my labels, measured by Cohen's kappa, stayed above 0.6.
>
> Then I ran it against the real judge model. It failed my own release gate. It would have auto-sent 10.3 percent of cases that I had labeled as needing a human. The ceiling was 5 percent. So the script refused to write a threshold.
>
> I looked at what separated my two groups. Every escalate case the judge actually scores was one of two kinds: a predicted price from three or four peers, or a contract expiring in 23 to 29 days. So I put those two rules in the judge prompt as explicit anchors. I did not change my labels or raise the ceiling. Two more runs gave a threshold of 0.85, kappa 1.00, and zero false auto-sends.
>
> I say the caveat myself. That is 32 cases, I tuned the prompt against them, and the judge is not deterministic. It missed three cases on one run and four on the next before the fix. So a pass is real, but weak evidence.

### Memory that compounds (30 seconds)

> When a reviewer corrects a flagged fact, a background job writes it as a permanent list price, required part, or contract coverage, plus the matching graph edge. I tested that the next identical scenario is trusted with no review. And I watched it happen in the UI.

### What it does not prove (30 seconds)

> Four things I want you to hear from me. The data is synthetic. I ran the real GPT-4o intake over all 60 emails and the real agent over 40 of them, once. The agent finished 30 of the 40 correctly, sent 9 more to review with the right draft, and none went out wrong on the checks I scored. But intake resolved the right parts on only 44 of 60 emails, because it ignores a part number typed in the email, and duplicate detection was right on 4 of 10 pairs live. The test that scored 10 of 10 injects the answer key. Third, the seeded demo still uses scripted stand-ins, so it proves plumbing, not model judgment. Fourth, the judge has not scored those live drafts yet. Those are the next things I would build.

## The lessons from the rebuild (pick one or two)

Use these for beat (d), or when asked "what did you learn".

1. **A check that compares model output to other model output is not a guardrail.** In Phase 3 the discount check compared the draft's contract to the draft's own customer. Both were written by the model, so a made-up customer with a good contract passed. I fixed it by anchoring on the customer stored on the request. Source: `../phase3-interview.md`.
2. **A mock proves you call the queue, not that the queue works.** Every task was green with 650 tests. A final review found the worker could not start and nothing created the queue tables. A real smoke test then found a third bug on Windows. Source: `../phase6-interview.md`.
3. **A calibration gate is only useful if it can fail.** Mine failed on the first real run, which is the reason to have it. Source: `../phase5-interview.md`.
4. **Measure each layer before optimizing.** A page that "loaded slowly" had a 14 ms API and a 20-second layout. Source: `../phase7-interview.md`.
5. **A test that injects the answer key does not test the step before it.** My dedupe test scored 10 of 10 because it fed in the correct SKU sets. Run end to end with the real model, the same classifier got 4 of 10, because intake failed to resolve the parts. Source: `backend/data/live_run_report.json`.
6. **A non-goal in a spec is a decision the user must be able to see.** I had quietly dropped the live graph view. Source: `../phase7-interview.md`.

## What I never say

- No company names, no work metrics, no work outcomes.
- No claim that the POC has real users, real data, or production traffic.
- No claim that the demo shows a live model. The seeded demo uses scripted stand-ins.
- No claim that dedupe works at 10 of 10. That number comes from a test that injects the answer key. Live it was 4 of 10.
