import json
import random
import re
from pathlib import Path

SCENARIO_TYPES = [
    "discontinued_swap",
    "missing_required_part",
    "discount_category_mismatch",
    "duplicate_pair",
    "revision_pair",
    "clean_distinct",
]


def _customer_contact(customer, rng):
    contact = rng.choice(customer["contacts"])
    return {"name": customer["name"], "contact": contact["name"]}


def _select_discontinued_swap(catalog, customers, rng, count, next_index):
    candidates = [s for s in catalog if s["discontinued"] and s["replaced_by"]]
    if len(candidates) < count:
        raise ValueError(f"need {count} discontinued SKUs with a replacement, found {len(candidates)}")
    cases = []
    for i, sku in enumerate(rng.sample(candidates, count)):
        customer = rng.choice(customers)
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "discontinued_swap",
            "customer": _customer_contact(customer, rng),
            "entities": {"customer_id": customer["customer_id"], "sku_id": sku["sku_id"], "sku_name": sku["name"]},
        })
    return cases


def _select_missing_required_part(catalog, customers, rng, count, next_index):
    candidates = [s for s in catalog if s["requires"] and not s["discontinued"]]
    if len(candidates) < count:
        raise ValueError(f"need {count} SKUs with a required part, found {len(candidates)}")
    cases = []
    for i, sku in enumerate(rng.sample(candidates, count)):
        customer = rng.choice(customers)
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "missing_required_part",
            "customer": _customer_contact(customer, rng),
            "entities": {"customer_id": customer["customer_id"], "sku_id": sku["sku_id"], "sku_name": sku["name"]},
        })
    return cases


def _select_discount_category_mismatch(catalog, customers, rng, count, next_index):
    skus_by_category = {}
    for sku in catalog:
        if not sku["discontinued"]:
            skus_by_category.setdefault(sku["category"], []).append(sku)

    triples = []
    for customer in customers:
        for contract in customer["contracts"]:
            uncovered = [c for c in skus_by_category if c not in contract["covered_categories"]]
            for category in uncovered:
                for sku in skus_by_category[category]:
                    triples.append((customer, contract, sku))

    if len(triples) < count:
        raise ValueError(f"need {count} discount-mismatch cases, found {len(triples)}")

    cases = []
    for i, (customer, contract, sku) in enumerate(rng.sample(triples, count)):
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "discount_category_mismatch",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "contract_id": contract["contract_id"],
                "covered_categories": contract["covered_categories"],
                "sku_id": sku["sku_id"],
                "sku_name": sku["name"],
                "sku_category": sku["category"],
            },
        })
    return cases


def _select_duplicate_pair(catalog, customers, rng, pair_count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    index = next_index
    for p in range(pair_count):
        customer = rng.choice(customers)
        site = rng.choice(customer["sites"])
        line_items = rng.sample(eligible, k=rng.randint(1, 2))
        shared_entities = {
            "customer_id": customer["customer_id"],
            "site_id": site["site_id"],
            "sku_ids": [s["sku_id"] for s in line_items],
            "sku_names": [s["name"] for s in line_items],
            "pair_id": f"dup-{p + 1:04d}",
        }
        for role in ("first", "second"):
            cases.append({
                "case_id": f"sc-{index:04d}",
                "scenario_type": "duplicate_pair",
                "customer": _customer_contact(customer, rng),
                "entities": {**shared_entities, "pair_role": role},
            })
            index += 1
    return cases


def _select_revision_pair(catalog, customers, rng, pair_count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    index = next_index
    for p in range(pair_count):
        customer = rng.choice(customers)
        site = rng.choice(customer["sites"])
        original_items = rng.sample(eligible, k=rng.randint(1, 2))
        remaining = [s for s in eligible if s not in original_items]
        added_item = rng.choice(remaining)
        pair_id = f"rev-{p + 1:04d}"

        cases.append({
            "case_id": f"sc-{index:04d}",
            "scenario_type": "revision_pair",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "site_id": site["site_id"],
                "sku_ids": [s["sku_id"] for s in original_items],
                "sku_names": [s["name"] for s in original_items],
                "pair_id": pair_id,
                "pair_role": "original",
            },
        })
        index += 1

        revised_items = original_items + [added_item]
        cases.append({
            "case_id": f"sc-{index:04d}",
            "scenario_type": "revision_pair",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "site_id": site["site_id"],
                "sku_ids": [s["sku_id"] for s in revised_items],
                "sku_names": [s["name"] for s in revised_items],
                "pair_id": pair_id,
                "pair_role": "revision",
            },
        })
        index += 1
    return cases


def _select_clean_distinct(catalog, customers, rng, count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    for i in range(count):
        customer = rng.choice(customers)
        line_items = rng.sample(eligible, k=rng.randint(1, 3))
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "clean_distinct",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "sku_ids": [s["sku_id"] for s in line_items],
                "sku_names": [s["name"] for s in line_items],
            },
        })
    return cases


def select_cases(config, catalog: list[dict], customers: list[dict]) -> list[dict]:
    # offset seed so scenario selection doesn't correlate with catalog_gen's or customer_gen's draws
    rng = random.Random(config.seed + 2)
    per_type = config.scenarios_per_type
    pair_count = per_type // 2

    cases: list[dict] = []
    cases += _select_discontinued_swap(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_missing_required_part(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_discount_category_mismatch(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_duplicate_pair(catalog, customers, rng, pair_count, len(cases) + 1)
    cases += _select_revision_pair(catalog, customers, rng, pair_count, len(cases) + 1)
    cases += _select_clean_distinct(catalog, customers, rng, per_type, len(cases) + 1)
    return cases


PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "docs" / "prompts" / "scenarios_gen_prompt.md"


def _load_prompt_template() -> str:
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    match = re.search(r"```\n(You write realistic.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError(f"could not find prompt template block in {PROMPT_TEMPLATE_PATH}")
    return match.group(1)


def build_prompt_batches(cases: list[dict], batch_size: int = 10) -> list[str]:
    template = _load_prompt_template()
    batches = []
    for i in range(0, len(cases), batch_size):
        batch = cases[i : i + batch_size]
        batch_json = json.dumps(
            [
                {
                    "case_id": c["case_id"],
                    "scenario_type": c["scenario_type"],
                    "customer": c["customer"],
                    "entities": c["entities"],
                }
                for c in batch
            ],
            indent=2,
        )
        batches.append(template.replace("{{BATCH_CASES_JSON}}", batch_json))
    return batches


def write_prompt_batches(batches: list[str], prompts_dir: Path) -> list[Path]:
    prompts_dir.mkdir(parents=True, exist_ok=True)
    # Find the max numeric index from existing batch_NNN.md files
    existing_indices = []
    for path in prompts_dir.glob("batch_*.md"):
        match = re.search(r"batch_(\d+)\.md", path.name)
        if match:
            existing_indices.append(int(match.group(1)))
    next_index = max(existing_indices) + 1 if existing_indices else 1
    paths = []
    for offset, batch in enumerate(batches):
        path = prompts_dir / f"batch_{next_index + offset:03d}.md"
        if path.exists():
            raise FileExistsError(f"{path} already exists; will not overwrite")
        path.write_text(batch, encoding="utf-8")
        paths.append(path)
    return paths


# Scenario types whose label is distinctive enough on its own that a single strong signal
# word appearing in the email is a reliable sign of a leak, even if the other half of the
# label (e.g. "pair") doesn't appear. Word-boundary matched, same as the all-words check.
_LABEL_LEAK_SIGNAL_WORDS = {
    "discontinued_swap": ["discontinued"],
    "duplicate_pair": ["duplicate"],
    "revision_pair": ["revision"],
}


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def ingest_responses(cases: list[dict], responses_dir: Path) -> tuple[list[dict], dict[str, str]]:
    cases_by_id = {c["case_id"]: c for c in cases}
    email_text_by_id: dict[str, str] = {}
    rejected: dict[str, str] = {}

    for response_path in sorted(responses_dir.glob("*.json")):
        try:
            entries = json.loads(response_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # every case_id in this batch stays unresolved; caught by the missing-case check below

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            case_id = entry.get("case_id")
            if case_id not in cases_by_id:
                continue
            email_text = entry.get("email_text", "")
            scenario_type = cases_by_id[case_id]["scenario_type"]
            label_words = scenario_type.split("_")

            if not isinstance(email_text, str) or not email_text.strip():
                rejected[case_id] = "empty email_text"
                email_text_by_id.pop(case_id, None)
                continue

            lowered = email_text.lower()
            signal_words = _LABEL_LEAK_SIGNAL_WORDS.get(scenario_type, [])
            leaks = any(_contains_word(lowered, word) for word in signal_words) or all(
                _contains_word(lowered, word) for word in label_words
            )
            # A response file processed later (sorted by filename, e.g. a re-batch round) overrides
            # an earlier verdict for the same case_id: last write wins, and a case never ends up in
            # both `accepted` and `rejected` at once.
            if leaks:
                rejected[case_id] = "email_text leaks scenario_type label"
                email_text_by_id.pop(case_id, None)
            else:
                email_text_by_id[case_id] = email_text
                rejected.pop(case_id, None)

    accepted = []
    for case in cases:
        case_id = case["case_id"]
        if case_id in email_text_by_id:
            accepted.append({**case, "email_text": email_text_by_id[case_id]})
        elif case_id not in rejected:
            rejected[case_id] = "missing from any response file"

    return accepted, rejected


def rebatch_rejected(cases: list[dict], rejected: dict[str, str], prompts_dir: Path, batch_size: int = 10) -> list[Path]:
    rejected_cases = [c for c in cases if c["case_id"] in rejected]
    batches = build_prompt_batches(rejected_cases, batch_size)
    return write_prompt_batches(batches, prompts_dir)


def write_scenarios(accepted_cases: list[dict], path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(accepted_cases, key=lambda c: c["case_id"])
    path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
