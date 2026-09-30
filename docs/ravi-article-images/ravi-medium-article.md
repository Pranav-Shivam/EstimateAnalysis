# Ravi Sent the Same Email to Three Suppliers. The One With a Knowledge Graph Won.

[Image: 01-cover.png | Medium header image, upload as the first image]

*Every quoting agent gets sold on speed. Speed gets you into the room. It doesn't keep you there. This is the story of one quote email, the 12 minutes after it landed, a second email from the same job that nearly got quoted twice, and what a system like this is worth over a full year. It's also the clearest way I know to explain agent engineering, eval engineering, and graph engineering, and why a business needs all three.*

Eight months before this story starts, a plumber on a hospital job stood in front of an open wall holding a faucet he couldn't install.

The faucet was fine. The order was fine. It just didn't include the concealed mounting carrier that a wall-mount faucet bolts onto. Nobody asked for one, so nobody shipped one. The crew lost two days waiting for parts.

A rep at the distributor logged the return, fixed the order, and moved on. Nobody at the company remembers that plumber's name today.

The system does.

Hold on to that. It comes back.

---

I build AI automation for enterprise clients, most of it in the space where emails turn into priced estimates. What follows is a composite. The company, the people, and the numbers are changed, because the originals aren't mine to share.

The shape is exact.

## The Problem: A Quote Desk That Can't Keep Up

*Monday, 8:02 am, before any of this was built.* Meera opens the shared quote inbox at Northline's east branch. There are 63 new emails since Friday evening.

The first one says "need 40 wall-mount faucets and 12 steel sinks, hotel job." No part numbers. Meera knows wall-mount faucets need mounting carriers, so she adds them. The rep next to her, three months into the job, wouldn't have.

The third email asks for a sink that was discontinued last month. She spends 20 minutes on the phone finding the replacement, then checks whether the customer's contract discount covers it. It doesn't. She almost applied it anyway.

The ninth email is the same hotel job as the first, sent by the contractor's site supervisor. Meera doesn't know that. Neither does her colleague at the west branch, who quoted the same job yesterday, at a different price.

By 11:30 she has finished 5 quotes. Two of those contractors have already booked with someone else.

Nobody at Northline is doing a bad job. The job itself is set up to fail.

**The problem in one sentence:** distributors lose jobs they should win, because turning a free-text quote email into a correct, priced estimate takes a skilled person most of an hour, and the knowledge needed to get it right lives in people's heads instead of in the system.

[Image: 02-problem-statement.png | Caption: One problem, four symptoms, and what a solution has to do.]

That one problem shows up four ways:

1. **Slow.** About 45 minutes per quote, and 200 quote emails a day, is 150 rep hours of work every day. One distributor that actually measured its turnaround found a median of 13 to 14 hours. Meanwhile about 78% of B2B buyers go with the first credible proposal, and distributors lose over 40% of potential wins once a quote takes longer than 24 hours.
2. **Wrong.** Discontinued items, missing required parts, discounts applied to the wrong category. None of these mistakes are visible in the email. They live in how products, contracts, and customers connect, and they show up later as returns, callbacks, and credit notes.
3. **Duplicated.** The same job arrives from two people, or from one person emailing two branches, or gets resent with one line changed. That means double the work, two prices sent to one customer, and a pipeline report that counts the same job twice. Simple matching fails in both directions: an exact match misses a reworded duplicate, and a loose match mistakes a real revision, like a changed finish, for a duplicate.
4. **Forgetful.** When Meera fixes a price or adds a carrier, that fix lives in one quote. The next rep makes the same mistake. And when Meera leaves the company, everything she knows leaves with her.

**What a solution has to do.** The rest of this article is how each of these gets built:

- **Read any email or attachment** and turn it into a structured request. *Built with intake and the agent loop.*
- **Catch duplicates and revisions** before doing any work. *Built with the dedupe agent.*
- **Get the relationships right:** substitutes, required parts, contract coverage. *Built with the knowledge graph.*
- **Know when it's unsure,** and ask a person the right question. *Built with evals and human in the loop.*
- **Remember every correction,** so it never repeats a mistake. *Built with memory and LLMOps.*

> **Business readers, a shortcut:** the next several sections are the engineering: how the system is built, with schemas and code. If you want the business impact (time saved, revenue won, margin kept, and where to invest), jump straight to **"What This Is Worth: One Year, Worked Out."** The story is still here whenever you want it. It's the same problem, told from the inside.

Staying for the story? Look for **In plain terms** notes for what each piece does for the business, and **Under the hood** for the schemas, thresholds, and code.

## A 60-Second Glossary

Skip this if you build agents for a living.

- **Agent:** an AI model that doesn't just answer. It takes steps: looks things up, uses tools, checks its own work, then answers.
- **Context window (working memory):** everything the model can see at one time. If it isn't in there, the model doesn't know it.
- **RAG and vector search:** a way of finding documents that *read like* your question. Good at "find me the contract." Bad at "does this contract cover that product."
- **Knowledge graph:** a map of how your business things connect. This customer holds that contract, which covers this category, which contains that product.
- **Eval:** an automated grader. It scores every answer before anyone sees it.
- **Human in the loop:** a person reviews only the answers the eval isn't sure about.
- **Dedupe:** catching when two emails are really the same request, so you don't do the work twice.
- **LLMOps:** the plumbing that measures, fixes, and safely ships improvements to the whole system over time.

## 5:40 pm, Thursday. The Email.

Ravi is a project manager at a general contractor, bidding on a hotel renovation. It's the end of a long day, and he types the same email to three plumbing supply distributors:

> "Need 40 wall-mount faucets, 12 steel sinks, and fittings for a hotel job. Delivery by March 10."

No part numbers. No format. Twelve days until delivery.

One sentence of free text that somebody has to turn into a priced quote.

Two of those distributors have gone home for the night. Their reps will open this tomorrow, look up each item, check Ravi's account, discover a problem with one of the sinks, call a supplier, and send something back in the afternoon.

The third distributor, call it Northline Supply, will have a complete estimate in Ravi's inbox by 5:52 pm.

Ravi will book with them before the other two finish their coffee.

That's the part that's easy to sell. What's interesting is what happened inside those 12 minutes, because Ravi's one sentence was hiding three expensive mistakes. A tired rep catches maybe one. The agent caught all three.

And the next morning, a second email about the same job would try to make Northline quote it twice.

[Image: 03-the-race.png | Caption: Same email, three suppliers. Only one answered before Ravi booked.]

## Why 12 Minutes Is a Revenue Number

Remember the numbers from the problem: about 78% of buyers go with the first credible proposal, and distributors lose over 40% of potential wins past 24 hours. Speed protects price too. Research cited by Broadn found manufacturers who quote fast can price up to 3% higher without losing the customer.

So 12 minutes against tomorrow afternoon isn't an efficiency win.

It's who gets the job.

> **In plain terms:** your quote turnaround is a sales metric, not an operations metric. Every hour a quote sits in an inbox is an hour a competitor can win the job.

## Fast and Wrong Is Worse Than Slow

Most quoting automation makes the quote fast, and that's all it does. But speed only fixes the first symptom. Ravi's one sentence carried the second one, three times over:

1. **One sink he wanted, SKU 2210, was discontinued last month.**
2. **His faucets need mounting carriers.** He didn't ask for them. Almost nobody does.
3. **His 8% contract discount doesn't apply to the sink that replaces 2210.** It sits in a pricing category his contract doesn't cover.

None of this is visible in the text. All of it is visible in how the company's data connects.

The agent caught all three. Not because the model is smarter than a rep.

Because of how the system around the model was built.

## 5:40 and 8 Seconds. The Agent Reads It.

[Image: 04-architecture.png | Caption: The full system. Harness on the left, LLMOps on the right. Follow the numbers.]

The architecture has two halves. The left side is the harness: everything that happens during one run. The right side is LLMOps: everything that makes the next run better.

We'll follow Ravi's email through the left side first.

**The model only ever sees working memory.** Each run starts by assembling a context window from three inputs: the email, the thread history, and a system prompt that defines the agent's job and limits. Everything inside that run is ephemeral. When it ends, working memory is gone. Anything worth keeping has to be written somewhere else, on purpose.

**The agent loop does the work.** The model doesn't answer in one shot. It plans, calls a tool, reads the result, and decides what's next. For Ravi, the tools are the unglamorous ones that matter: match the customer in the CRM, search the price book, check stock, predict a price when a SKU has no history. The loop only ends when guardrails pass: every line priced, every price in range, no discount the contract doesn't allow.

Eight seconds in, one sentence of free text has become a structured request.

**Under the hood:** intake turns every email and attachment (PDF, spreadsheet, even a photo of a handwritten list) into one typed object. Everything downstream works on this object, never on raw text.

```json
{
  "request_id": "Q-101",
  "received_at": "2026-02-26T17:40:00",
  "branch": "east",
  "sender": {"email": "ravi@raviconstruction.com", "account_id": "ACC-4471"},
  "site": {"raw": "hotel job", "normalized": null},
  "need_by": "2026-03-10",
  "lines": [
    {"raw": "wall-mount faucets", "qty": 40, "part": null},
    {"raw": "steel sinks",        "qty": 12, "part": null},
    {"raw": "fittings",           "qty": null, "part": null}
  ]
}
```

Guardrails are code, not prompt text. "Never apply a discount the contract doesn't cover" is a check that blocks the loop from finishing. It isn't a sentence the model can talk itself out of under pressure.

> **In plain terms:** the AI reads messy emails the way a new hire would, then fills out the same quote form your reps use. It can't skip a field, and it can't give a discount the contract doesn't allow.

## 5:40 and 40 Seconds. Four Memories Wake Up.

A vector store feels like memory. It's one kind of memory, and it's the wrong kind for half of what a quoting agent needs to know. So there are four.

**Procedural memory: how to act.** Rules in files, loaded as skills (think skill.md). Bulk discount above 25 units. Rush fee under 14 days. Ravi's order triggers both.

**Semantic memory: what's true.** A vector store of durable facts. Ravi's company gets 8%. They do hotels and hospitality. They prefer one brand of fittings.

**Episodic memory: what happened.** SQL plus vectors, holding dated events and past conversations. Ravi's last 5 quotes. The fact that the last time he ordered wall-mount faucets, he called back two days later.

**The knowledge graph: how it all connects.** Customers, people, contracts, pricing categories, product families, SKUs, substitutes, projects, and required parts, stored as entities with typed relationships.

The first three are standard.

The fourth is where the three mistakes get caught.

> **In plain terms:** your best rep carries four kinds of knowledge in their head: the rules, the customer, the history, and how everything connects. This gives the system all four, and it never goes on vacation.

## 5:41. The Part a Vector Store Gets Wrong.

Picture the vector-only version of this system. It retrieves three chunks, and every one of them is correct:

- A product notice: SKU 2240 replaces the discontinued 2210.
- Ravi's contract: 8% on covered categories.
- An install guide: wall-mount faucets are installed on a concealed carrier.

The model reads those, swaps in 2240 (good), applies 8% to it (wrong), and never adds a carrier, because "installed on a carrier" never turns into "put a carrier on the order."

Three correct chunks. One wrong quote. Off by $2,474.

[Image: 05-graph-vs-vector.png | Caption: Three correct chunks, one wrong quote. Three connected paths, one right quote.]

That's the whole case for GraphRAG. Similarity search finds things that read alike. It has no way to intersect them. Graph traversal follows things that are actually connected.

Here's what the graph walked:

```
(:SKU {id: "2210", status: "discontinued"})
    -[:REPLACED_BY]-> (:SKU {id: "2240"})
    -[:PRICED_IN]->   (:PricingCategory {code: "B"})

(:Customer {name: "Ravi Construction"})
    -[:HOLDS]->       (:Contract {discount: 0.08})
    -[:COVERS]->      (:PricingCategory {code: "A"})
    // no COVERS edge to category B

(:SKU {id: "WM-FAUCET"})
    -[:REQUIRES]->    (:SKU {id: "CARRIER-7"})
```

Three questions, three answers:

- **Swap 2210 for 2240.**
- **No 8% on 2240.** On 12 sinks, that's $394 of margin a rushed rep would likely have given away.
- **Add 40 carriers.** That's $2,080 of order value Ravi didn't ask for, and a lost install week he'll never have.

The benchmarks line up with what this feels like in production. Tian Pan's write-up of enterprise GraphRAG results reports 86% accuracy on multi-hop questions where vector RAG managed 32%. The more hops, the wider the gap.

> **In plain terms:** a search engine finds the right pages. It can't tell you that page 4 cancels out page 12. The graph can, and it shows its work.

## How the Graph Knows Any of This

It isn't magic at query time. It's work done before the query ever arrives.

**Built offline.** Entity extraction pulls products, customers, people, and contracts out of the catalog, CRM, contracts, and transaction history. Relationship extraction connects them. Community detection (Leiden, the same algorithm Microsoft's GraphRAG uses) groups related entities, and each group gets a summary.

**Queried two ways.** Local search starts from one entity, like SKU 2210, and fans out. That's what Ravi's quote used. Global search reads across the community summaries, for questions like "what's eating our margin on hotel jobs this quarter?"

**Skipped most of the time.** This is the part people get wrong. One analysis of enterprise RAG traffic estimated about 80% of queries are simple lookups best served by vector search, about 15% need graph reasoning, and about 5% need full agentic planning. Run everything through the graph and you pay a latency tax on the 80% that didn't need it.

So a hybrid retrieval router sits in front of all four memories and picks per question. Ravi's customer lookup goes to vector. His last 5 quotes go to SQL. The substitute and the carrier go to the graph.

**Under the hood:** the graph schema is small on purpose. Fifteen edge types cover almost every question a quoting agent asks.

```
Nodes:  Customer, Person, Contract, PricingCategory, ProductFamily,
        SKU, Project, Site, QuoteRequest, Quote

Edges:  WORKS_FOR, HOLDS, COVERS, IN_FAMILY, REPLACED_BY, PRICED_IN,
        REQUIRES, HAS_PROJECT, AT_SITE, FOR_PROJECT,
        DUPLICATE_OF, REVISION_OF, VARIANT_OF, SUPERSEDES, PRICE_VARIANCE
```

The router is mostly rules, with a small classifier for the ambiguous cases. "Price or stock for a known SKU" goes to SQL. "Anything about this customer" goes to vector. "Substitute, compatibility, coverage, or required part" goes to the graph. Every graph answer returns its path as well as its result, because the eval needs it in the next step.

## 5:42. The Agent Doesn't Trust Itself.

The draft comes out at $18,400. Add the carriers and it's $20,480.

Before any human sees it, an eval scores it.

The eval is an LLM-as-a-judge. It checks prices against the price book, discounts against the contract, and every graph decision against the path that produced it. It returns a confidence score from 0 to 1.

The rule is simple. At 0.85 or above, the estimate goes straight to the customer. Below it, a person looks first.

Ravi's scored 0.71.

Not a failure. A flag.

```json
{
  "score": 0.71,
  "route": "human_review",
  "weak_hop": "(:SKU 2240)-[:PRICED_IN]->(:PricingCategory B)",
  "reason": "SKU 2240 price predicted, no quote history",
  "checked": ["contract_discount", "bulk_rule", "rush_fee", "required_accessory"],
  "passed":  ["contract_discount", "bulk_rule", "rush_fee", "required_accessory"]
}
```

SKU 2240 had never been quoted before. Its price was predicted, not looked up. The agent knew exactly which number it wasn't sure about, and said so.

**Under the hood:** three details decide whether this eval is trustworthy.

- **The judge is a different model from the agent.** Same-model judging tends to share the same blind spots.
- **The threshold is calibrated, not chosen.** Take a few hundred quotes that humans reviewed. Find the score above which reviewers almost never changed anything. That's your line. Re-check it every time the model, prompt, or graph changes.
- **The metric that matters is false auto-sends.** How often did a quote go out untouched that a reviewer would have changed? Set a ceiling you're comfortable with, and gate every release on it.

**One honesty check.** An LLM judging an LLM can still be confidently wrong. The evidence path helps, because the judge checks a chain of facts instead of a vibe. But 0.85 isn't a magic number. It's whatever your reviewers' data says it should be.

> **In plain terms:** every quote gets graded before it leaves the building. The confident ones go out on their own. The rest go to a person, with a note saying exactly what to check.

## 5:44. Meera Gets One Question, Not Fourteen.

Meera is the rep on shift. Her screen doesn't say "low confidence, please review." It says: one price, predicted, here's why.

This is the difference between a review queue people trust and one they rubber-stamp.

She doesn't re-check 14 line items. She opens the supplier sheet for SKU 2240. The real price runs 12% higher than predicted. She fixes it, +$50 per sink, $600 total, and approves.

## 5:52 pm. Sent.

Final estimate: $21,080. Substitute swapped. Carriers added. The discount that shouldn't apply, didn't.

The machine took about 2 minutes. Meera took about 8. That's fine. That's the system working.

## Friday, 7:15 am. Kiran Sends the Same Order to a Different Branch.

Ravi's site supervisor, Kiran, is standing on the hotel site at dawn. He doesn't know Ravi already asked for pricing. He's worried nobody ordered anything, so he emails Northline's *west* branch from his phone:

> "Hi, need pricing for Hotel Harbor, 14 Harbour Rd. 40 WM faucets, 12 SS sinks 18ga + carriers. Thanks, Kiran"

Different person. Different branch. Different email address, and a personal one at that. Different words for the same parts.

Same job.

This happens every single day in distribution. Two people from one company. One person emailing two branches. A resend with one line changed. It's also where most quoting systems quietly burn money.

Here's what happens without dedupe. Kiran's email looks brand new, so it kicks off the full agent loop again. That means another round of CRM lookups, price book searches, graph traversal, and evals. Another human review, because that substitute still flags. And probably a different price, because the west branch has never seen Kiran's gmail address and can't connect him to Ravi's 8% contract.

Ravi ends up with two quotes from the same company, at two prices, for one job. He calls and asks for the lower one. Meanwhile the sales dashboard shows $42k of pipeline for a $21k order.

This is a known problem in distribution. Orbweaver's write-up of the quote intake process calls out both halves of it: duplicate quote opportunities inflate the pipeline, and duplicates across regions create internal competition that cuts into profit.

At Northline, Kiran's email never reaches the agent loop. It hits the dedupe agent first.

[Image: 06-dedupe-agent.png | Caption: One job, three emails, one price. Cheap checks first, relationships over strings, two fingerprints instead of one.]

The dedupe agent runs cheap checks before anything expensive. Each one narrows the field:

1. **Email domain: no match.** raviconstruction.com vs gmail.com. A naive system stops here and calls Kiran a new customer. This one knows gmail.com is too common to be a matching key at all. That's standard practice in entity resolution: skip oversized groups like "everyone on gmail.com," because they explode the number of comparisons.
2. **Site address: 0.94.** "Plot 14, Harbor Road, Suite 2" and "14 Harbour Rd" both normalize to `14 HARBOR RD`.
3. **Zip code: exact match.**
4. **Contract: linked through the graph.** Kiran isn't in the CRM. But last spring he signed for a delivery on another Ravi Construction job, and that event left an edge behind: `(:Person Kiran)-[:WORKS_FOR]->(:Customer Ravi Construction)`. Strings can't join two different email addresses. Relationships can.
5. **Line items: same keys.** Both emails normalize to the same part numbers, quantities, and sizes.
6. **Line values: same.** Finish, gauge, and mounting type all match.

The raw email hash never gets a vote. The two emails use different words, so the hash says "different," which is useless.

The graph writes one node and one edge:

```
(:QuoteRequest Q-102 {from: "Kiran", branch: "west"})
    -[:DUPLICATE_OF {score: 0.96}]-> (:QuoteRequest Q-101 {from: "Ravi"})
```

Q-101 is already approved at $21,080. So there's no second agent run and no second review. Kiran gets the same estimate Ravi got, on the same thread, at the same price, in about 4 seconds. The west branch rep gets a short note: this job is already quoted, here's the link.

**Merges are edges, not deletes.** Q-102 still exists. It points at Q-101 and records why. Graph-based entity resolution tools like HASH work the same way, recording diff and merge history so every resolution decision stays transparent and reversible.

> **In plain terms:** when two people from the same customer ask for the same thing, they get one answer and one price. Your team does the work once, and your pipeline report stops counting the same job twice.

## Friday, 9:05 am. Ravi Books.

Five minutes later, across town, a rep at one of the other distributors opens Ravi's original email with his coffee.

He keys in the faucets. He looks up the sinks. He sees 2210 is discontinued and calls a supplier about a replacement. He applies Ravi's 8% to the whole order, because that's what the account says. He sends his quote at 11:20 am, missing the carriers and giving away $394 in discount.

The job was booked two hours earlier.

## Monday, 3:05 pm. Same Parts. Different Quote.

Ravi emails again:

> "Same as before, but the owner wants brushed nickel on the faucets and 16 gauge sinks."

This is the email that breaks every hash-based dedupe I've seen.

Look at it the way a naive system does. Same part numbers. Same quantities. Same sizes. Hash those keys and you get the same fingerprint as Q-101. Roughly 90% of the fields match. So the naive system says "duplicate" and resends Thursday's chrome quote. Wrong finish, wrong gauge, wrong price, sent fast and confident.

The opposite failure is just as common. Hash the full record, and every tiny formatting difference (a space, "18ga" vs "18 gauge") makes two identical requests look different. Now you're quoting the same job twice again.

**The fix is two fingerprints, not one.**

- **The key fingerprint** answers *what* is being asked for: part numbers, quantities, sizes.
- **The value fingerprint** answers *how*: finish, gauge, mounting type, options.

Monday's email matches Thursday's on every key, and differs on 2 of 14 values. Same keys with different values isn't a duplicate. It's a revision.

```
(:QuoteRequest Q-103) -[:REVISION_OF {changed_lines: 2}]-> (:QuoteRequest Q-101)
(:QuoteRequest Q-103) -[:SUPERSEDES]-> (:Quote Q-101-v1)
```

The agent doesn't rerun the whole quote either. It reprices only the 2 lines that changed:

- Brushed nickel faucets: +$1,584
- 16 gauge sinks: +$420
- New total: **$23,084**

Q-101 is marked superseded. Both Ravi and Kiran get the revision, so nobody on site is holding the old chrome price.

**Under the hood:** here's the core of the classifier. The weights and thresholds come from labeled pairs your reviewers already resolved, not from intuition.

```python
def key_fp(q):
    # WHAT is being asked for: canonical, order-independent
    return sha256(sorted((l.part, l.qty, l.size) for l in q.lines))

def value_fp(q):
    # HOW it is being asked for
    return sha256(sorted((l.part, l.finish, l.gauge, l.mount, l.options)
                         for l in q.lines))

def classify(new, cand):
    score = (0.30 * account_link(new, cand)       # graph: same customer?
           + 0.25 * address_sim(new, cand)        # normalized site address
           + 0.10 * zip_match(new, cand)
           + 0.35 * line_key_overlap(new, cand))  # Jaccard on (part, qty, size)

    if score < 0.60:
        return "DISTINCT"                          # full agent run
    if score < 0.85:
        return "HUMAN_REVIEW"                      # rep sees side-by-side diff
    if value_fp(new) == value_fp(cand):
        return "DUPLICATE_OF"                      # reuse, send to all requesters
    if new.account == cand.account and new.received_at > cand.received_at:
        return "REVISION_OF"                       # reprice changed lines only
    return "VARIANT_OF"                            # alternative spec, same job
```

Three details that took the most tuning:

- **Blocking comes first.** Only compare a new request against open quotes that share a site, zip, or account. Comparing against everything is quadratic and slow.
- **Normalize before you fingerprint.** "18ga," "18 gauge," and "18-GA" must become the same token, or the value fingerprint is noise.
- **Don't let the graph over-merge.** Simple connected-components logic can chain two separate jobs together through one weak link. That's why DUPLICATE_OF, REVISION_OF, and VARIANT_OF are different edge types instead of one "same as" edge.

> **In plain terms:** the system can tell the difference between "same order, sent twice" and "same parts, but the owner changed the finish." One gets the existing quote. The other gets a fast, partial re-price. Neither gets a wrong quote.

## The Following Tuesday. Sana.

Here's where most human-in-the-loop systems waste the human. Meera's fix lives in one quote and dies there. The next contractor who needs 2240 gets the same bad prediction and the same review.

Not here.

Every run's messages get saved to episodic memory. But consolidation doesn't happen on every run, because writing everything is how memory turns into noise. It runs after N new conversations. A cheaper summarizer model reads the batch and writes two things:

- **Durable facts** to semantic memory: "Ravi's company accepts substitutes when the brand matches."
- **New edges** to the graph: `(:SKU 2240)-[:PRICE_VARIANCE {vs_predicted: +0.12}]`

On Tuesday, a contractor named Sana asks for 8 of the same sinks.

The graph already knows 2240's real price. Her estimate scores 0.93 and goes out in 90 seconds. Nobody touches it.

If you read my last piece on CLAUDE.md files, this will look familiar. The failure there was accretion without a filter: rules piling up because adding is cheap and deleting is expensive. The /learn command in claude-fluency-toolkit fixes that by filtering at the moment of writing. It skips what's already recorded, skips what's obvious, and writes nothing if nothing qualifies. Consolidating after N conversations, instead of after every run, is the same idea one layer down.

Memory that writes everything becomes memory nobody can trust.

[Image: 07-quote-story-end-to-end.png | Caption: Ravi's email, end to end. The correction in step 10 is what makes Sana's quote skip review.]

## The Carrier Was Never Intelligence. It Was Memory.

Remember the plumber from the start? The one standing in front of an open wall on a hospital job, eight months ago?

That's where the carrier edge came from.

When that order got fixed, the correction went into episodic memory. The summarizer turned it into one line in the graph: `(:SKU WM-FAUCET)-[:REQUIRES]->(:SKU CARRIER-7)`.

Nobody at Northline remembers that plumber. Nobody had to. The graph did.

So when Ravi's email arrived eight months later, the agent didn't reason its way to "wall-mount faucets need carriers." It didn't need to be clever. It followed an edge that one bad week had written.

And Kiran's email got matched the same way: through an edge written when he signed for a delivery last spring.

That's the real product. Not a fast agent. An agent that never makes the same mistake twice, and never does the same work twice.

## The Loop Nobody Sees

Everything above happened in individual runs. The right half of the architecture is about all of them together.

**Trace.** Every run produces one trace, in Langfuse or LangSmith. Every tool call, every retrieval, every graph hop, every dedupe decision, every token.

**Eval and observe, side by side.** Eval asks whether the output was good, using the same judge and evidence paths as the runtime gate, but across hundreds of runs. Observe asks whether it was healthy: tokens, latency, errors, cost per quote. A correct quote that burned 40 seconds on graph traversal is still a problem.

**Diagnose.** When scores dip, the question isn't "is the model bad?" It's "which step broke?" Because every decision carries a path, you can usually point at the exact hop: a missing REQUIRES edge, a pricing category re-mapped upstream, a dedupe threshold merging jobs it shouldn't.

**Gate.** Fixes don't ship because they look right. They ship because they pass the eval set. Fail, and it's fix, re-run, re-trace, re-eval.

**Release.** A new prompt version, a model config change, a new tool, a tuned retrieval parameter, a dedupe weight, or a graph schema update. The improved prompt and config flow back into the next run.

**Under the hood:** the eval set builds itself. Every quote a rep reviews becomes a labeled example: the input, what the agent proposed, and what the human changed. After a few months, you have a regression suite drawn from your real business. Releases go to one branch first. They only roll out wider if false auto-sends and correction rates hold steady.

> **In plain terms:** the system gets checked the way you'd check a new employee. Every change is tested against real past quotes before it goes live, and rolled out one branch at a time.

## What This Is Worth: One Year, Worked Out

> **If you jumped here:** the system reads every quote email, catches duplicates and revisions before anyone does any work, and prices with the right substitutes, parts, and discounts. It auto-sends the quotes it's confident about, and sends the rest to a rep with the one thing to check. Every correction makes the next quote better. Here's what that's worth over a year.

Stories sell. Math closes. Here's a worked example for a mid-size distributor. Every assumption is written down so you can swap in your own.

[Image: 08-business-case.png | Caption: One year at a 200-quote-a-day distributor. Illustrative assumptions, listed at the bottom.]

**The assumptions:**

- 200 quote emails a day, 250 selling days: **50,000 a year**
- 15% are duplicates or revisions: **7,500**, leaving **42,500** unique requests
- $8,000 average quote, so **$340M** of unique quoted value a year
- 25% baseline win rate, 20% gross margin
- 45 minutes of manual handling per email, $45 an hour loaded rep cost
- With the system: 80% auto-send, 8 minutes of review for the rest, 3-minute checks on revisions

**Time.** Manual handling is 37,500 rep hours a year, about 150 hours every single day. With the system, reviews and revision checks come to about 1,300 hours. That's **roughly 36,000 hours back**, the work of about 18 full-time reps, worth about **$1.6M** a year. And every day, 150 hours of quoting work drops to about 5.

Those reps aren't the savings line. They're the growth line. They move from keying in line items to calling the customers who matter.

**Win rate.** If first-credible-quote speed lifts win rate by just 3 points, from 25% to 28%, that's **$10.2M** of new revenue on a $340M quote book. At 20% margin, about **$2M** of gross profit. Given that distributors lose over 40% of potential wins past 24 hours, 3 points is conservative.

**Margin kept.** If 3% of quotes carry a pricing error averaging $300, like Ravi's discount on the wrong category, blocking those saves about **$380k** a year.

**Order size.** If 5% of quotes are missing a required part averaging $600, and you win 28% of them, adding the part is about **$360k** of revenue a year. And every one of those is a callback, a return, or a failed install that never happens.

**Dedupe.** 7,500 emails a year answered without a full agent run. One price per job, no conflicting quotes to the same customer, and a pipeline report that finally matches reality.

**Total:** about **$4M a year** in combined capacity and gross profit, before counting fewer returns, faster collections, and a forecast your leadership can trust.

**What it costs.** Model spend is usually the smallest line. The real investment is getting your catalog, price book, contracts, and customer records into a state a machine can use, and building the review workflow your team will actually trust.

## Where to Invest, in This Order

If you're a business leader reading this and thinking "we need this," here's the order I'd build it in. It's roughly the order in which each piece pays for the next.

**1. Your data.** A clean catalog and price book. One customer master, not three. Contracts stored as data, not PDFs in a shared drive. This is the least exciting step and where most of the effort goes. Everything else depends on it.

**2. Intake and dedupe.** Turn every email and attachment into a structured quote request, and catch duplicates before anyone does any work. This is often the fastest payback, because it removes waste without changing how reps price.

**3. The agent and pricing tools.** Connect to your ERP, CRM, and stock. Encode pricing rules as skills. Put hard guardrails on discounts. This is where first drafts start appearing in minutes.

**4. Evals and the review workflow.** A confidence score on every quote, a review screen that shows reps *why*, and the tracing and release gates behind it. This is what makes auto-send safe enough to turn on.

**5. The knowledge graph.** Substitutes, required parts, contract coverage, and who works for whom. This is what turns a fast system into one that stops repeating mistakes.

**And be honest about the graph's cost.** It's the most expensive piece to keep correct. Extraction costs real money, and governance is where it really hurts: Atlan's write-up estimates ungoverned sources produce 30 to 40% more duplicate or ambiguous nodes. Two records for the same SKU, spelled two ways, and your substitute edge points at the wrong one. Start with vector. Add the graph for the questions that need relationships.

**Two roles you'll need that don't exist yet:** someone who owns the review queue and the thresholds, and someone who owns the data the graph is built from.

**Seven numbers to track from day one:** median quote turnaround, auto-send rate, correction rate after send, win rate, duplicate rate, false merge rate, and cost per quote. If you can't measure the first four today, that's step zero.

## What Northline Actually Got

Four wins from one week of email. None of them are "we saved a rep 45 minutes."

- **They won the race.** 12 minutes against next-day replies.
- **They looked like the expert.** The carriers Ravi forgot made the order $2,080 bigger and saved his crew a lost week.
- **They kept their margin.** $394 that a rushed rep would have given away.
- **They sent one price per job.** Kiran's duplicate got the existing quote in seconds. Monday's revision got a 2-line re-price instead of a full rerun or, worse, the old chrome quote.

## If This Is Your Inbox

If you run a distribution or manufacturing business and your team answers quote emails the way Supplier B does, it's not a people problem. It's a system problem, and it's a solvable one.

If you're an engineer building something like this, steal the architecture. The pieces that matter most are the least glamorous: structured intake, two fingerprints for dedupe, a calibrated eval gate, and a graph that learns from every correction.

This is the work I do every day with enterprise clients. If you want to talk through what it would look like for your business, or you're stuck on one of these pieces, reach out on LinkedIn: [your LinkedIn link]. I read every message.

## TL;DR

**For business readers:**

- About 78% of B2B buyers pick the first vendor with a credible proposal. Most distributors take 13 to 30 hours to respond.
- Speed only helps if the quote is right. The costly mistakes (discontinued items, missing parts, wrong discounts, duplicate quotes) hide in how your data connects.
- For a 200-quote-a-day distributor, the worked example comes to about 36,000 rep hours back and about $4M a year in capacity and profit.
- Invest in this order: data, intake and dedupe, the agent, evals and review, then the knowledge graph.

**For engineers:**

- Working memory is ephemeral. The agent loop plans, calls tools, and stops only when code-level guardrails pass.
- Four memories, four jobs: procedural, semantic, episodic, and a knowledge graph, behind a hybrid router.
- GraphRAG answers multi-hop questions vector search can't intersect, and returns the evidence path. Keep it off the roughly 80% of queries that don't need it.
- The eval is a different-model judge, calibrated against reviewer decisions. Gate releases on false auto-send rate.
- Dedupe runs before the agent loop: block cheaply, normalize, match on graph relationships, and use two fingerprints (keys and values) to tell duplicates from revisions.
- Merges are edges, not deletes. Human corrections become facts and edges, so the system stops repeating mistakes.
- LLMOps closes the loop: trace, eval, observe, diagnose, gate, release to one branch, then wider.

## Sources

- Baytech Consulting, "From Days to Minutes: Custom CPQ and Sales Velocity" (first-responder and response-time win rate data): https://www.baytechconsulting.com/blog/from-days-to-minutes-custom-cpq-sales-velocity.md
- Proton.ai, "RFQ Automation Software" (distributor interviews on quote turnaround): https://www.proton.ai/blog/rfq-automation-software
- Distribution Strategy Group, "Beyond the Spreadsheet: Transforming Order and Quote Processes": https://distributionstrategy.com/beyond-the-spreadsheet-transforming-order-quote-processes/
- Broadn, "Fast Quotes Boost Manufacturing Win Rates by Half": https://www.broadn.io/blogs/fast-quoting-increases-manufacturing-win-rates
- Orbweaver, "What Is the RFQ Process in the Electronic Components Supply Chain?" (duplicate quote opportunities across regions): https://www.orbweaver.com/?p=683
- Tian Pan, "GraphRAG vs. Vector RAG: The Architecture Decision Teams Make Too Late": https://tianpan.co/blog/2026-04-19-graphrag-vs-vector-rag-architecture-decision
- Ajay Srinivasan, "Graph RAG vs Vector RAG: Choosing the Right Architecture for Enterprise Use Cases" (hybrid router and query distribution): https://medium.com/@ajaysrinivasan87/graph-rag-vs-vector-rag-choosing-the-right-architecture-for-enterprise-use-cases-f3f6205f959f
- Atlan, "What Is GraphRAG? Architecture, Enterprise Use Cases, and RAG Comparison": https://atlan.com/know/what-is-graphrag/
- TigerGraph, "GraphRAG vs Vector RAG: Which Retrieval Approach Wins for Enterprise AI": https://www.tigergraph.com/blog/graphrag-vs-vector-rag/
- HASH, "Entity Resolution" (reversible merges and merge history in a graph): https://hash.ai/glossary/entity-resolution
- Apify, "Entity Resolution Engine" (blocking and skipping oversized keys like gmail.com): https://apify.com/that_red_bird/entity-resolver
- Pranav Shivam, "Your CLAUDE.md Is Growing 226% a Year. Nobody's Deleting Anything, On Purpose.": https://medium.com/@pranavsinghtomar/your-claude-md-is-growing-226-a-year-nobodys-deleting-anything-on-purpose-7a0efc6f854a
- Pranav Shivam, claude-fluency-toolkit (/learn command): https://github.com/Pranav-Shivam/claude-fluency-toolkit

*Somewhere tonight, a contractor is typing one tired sentence to three suppliers, and tomorrow morning his site supervisor will send the same list to a different branch. Two suppliers will answer tomorrow, twice, at two prices. One will answer tonight, once, with the part he forgot to ask for already on the order. Follow for more on agent engineering, eval design, and the parts of production AI that only show up after the demo.*
