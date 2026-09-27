# LLM-as-Judge Calibration

Researched 2026-09-27, feeds the eval-gate design (confidence threshold for auto-send vs human review) and ADR-0004's judge-vendor reasoning.

## Calibration methodology

**Galileo AI, "How to Calibrate Your LLM Judge With Human Annotations"**
https://galileo.ai/blog/calibrate-llm-judge-human-annotations

- Assemble a golden dataset of 50-200 human-labeled examples covering the full quality range: clean successes, edge cases, failures.
- Have 2-3 humans label production traces using the same rubric prompt the judge sees.
- Compute inter-annotator agreement: Cohen's kappa for 2 labelers, Krippendorff's alpha for 3+.

**Future AGI, "LLM-as-a-Judge in 2026: How It Works, When It Fails"**
https://futureagi.com/blog/llm-as-a-judge/

- Threshold bands: Cohen's kappa below 0.4 means an ambiguous rubric (fix the rubric, not the model); 0.4-0.6 is weak but tunable; above 0.6 is acceptable; above 0.8 is strong.
- Score threshold guidance: above 0.6 acceptable, above 0.8 production-ready.
- Strong LLM judges reach ~80% agreement with human evaluators, roughly the level humans reach with each other.
- Production-ready judge checklist: locked rubric, measured Cohen's kappa against human labels, position/verbosity bias controls, a cross-family check against a frontier judge.
- When agreement drops below threshold: inspect disagreements to determine if the judge prompt needs updating, or if outputs have drifted into territory the judge wasn't designed for.

## Judge reliability / escalation guarantees

**arXiv 2407.18370, "Trust or Escalate: LLM Judges with Provable Guarantees for Human Agreement"**
https://arxiv.org/pdf/2407.18370

Found via search, not read in full this session. Formal framework for when a judge should defer to a human rather than auto-decide; directly relevant to the human-in-the-loop gate design (the 0.85 auto-send threshold in the source article). Worth reading in full before finalizing the actual threshold value for this project.

## Practical takeaway for this project

The source article's 0.85 auto-send threshold should not be copied as a magic number. Per this research: build the golden set from real reviewer corrections first (this project has none yet since it's pre-data), then derive the threshold from where Cohen's kappa against human labels crosses an acceptable band (>0.6) or a strong band (>0.8), and re-check it every time the agent model, prompt, or graph schema changes, consistent with what the source article itself says ("0.85 isn't a magic number, it's whatever your reviewers' data says it should be").
