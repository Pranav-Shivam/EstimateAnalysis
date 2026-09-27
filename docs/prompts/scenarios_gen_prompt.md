# Scenario Email Generation Prompt

Used by `scenario_gen.py` (Phase 1, synthetic data generation). This is a template, not a finished prompt: the script fills in `{{BATCH_CASES_JSON}}` with a batch of real, already-decided cases and writes the result to a file under `backend/data/prompts/`. You paste that file's contents into Claude, ChatGPT, or any other chat platform, then save the raw reply to the matching file under `backend/data/responses/` so the ingest step in `scenario_gen.py` can parse it back.

The model's only job is writing believable, messy customer email text. It does not choose facts, entities, or the scenario label: those are decided programmatically before this prompt is built, and are handed to the model as given.

---

## Prompt template

```
You write realistic B2B quote-request emails for a plumbing and HVAC parts distributor. You will receive a JSON array of cases. For each case, write ONE email a real customer or contractor might send when requesting a quote, matching that case's scenario_type and using only the entities and facts given for that case.

Rules:
- Do not invent SKUs, customer names, part numbers, or facts not present in the case's data. Use exactly what's given.
- Do not state or hint at the scenario_type in the email. The email is the customer's raw request, not a description of the underlying data problem. For example, if scenario_type is "duplicate_pair" or "revision_pair", the email is just an ordinary quote request; it must not say "this is a duplicate" or "following up on my last email" unless that phrasing is itself part of the case data provided.
- Write like a real person: inconsistent formatting, occasional typos, vague quantities ("a few", "about 20"), informal sign-offs, sometimes missing pleasantries, sometimes multiple unrelated line items in one email.
- Vary tone and length across cases: some short and terse, some longer with context about a job site or project.
- Return ONLY a JSON array, one object per input case, no prose before or after it.

Output format, exactly one object per case:
[
  {
    "case_id": "<same case_id from input>",
    "email_text": "<the full email body as plain text>"
  }
]

Cases:
{{BATCH_CASES_JSON}}
```

## Input shape (what `scenario_gen.py` substitutes for `{{BATCH_CASES_JSON}}`)

A JSON array of case objects. Exact fields depend on `scenario_type`, but every case carries at minimum:

```json
{
  "case_id": "sc-0001",
  "scenario_type": "discontinued_swap",
  "customer": { "name": "...", "contact": "..." },
  "entities": { "...": "..." }
}
```

`scenario_type` is one of: `discontinued_swap`, `missing_required_part`, `discount_category_mismatch`, `duplicate_pair`, `revision_pair`, `clean_distinct`.

## Ingest expectations

The response file must parse as a JSON array matching the batch's `case_id`s one-to-one. `scenario_gen.py`'s ingest step rejects and reports (by `case_id`) any case that:
- is missing from the response,
- has an `email_text` that mentions the scenario_type or otherwise leaks the label,
- fails JSON parsing entirely for the batch.

Rejected cases get re-batched into the next prompt file rather than hand-edited, so every email in the final dataset actually came from the model.
