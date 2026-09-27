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
[
  {
    "case_id": "sc-0041",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Ironclad Plumbing",
      "contact": "Suresh Nair"
    },
    "entities": {
      "customer_id": "CUST-0070",
      "site_id": "SITE-0106",
      "sku_ids": [
        "SKU-0307"
      ],
      "sku_names": [
        "Heavy-Duty Belt Medium"
      ],
      "pair_id": "rev-0001",
      "pair_role": "original"
    }
  },
  {
    "case_id": "sc-0042",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Ironclad Plumbing",
      "contact": "Suresh Nair"
    },
    "entities": {
      "customer_id": "CUST-0070",
      "site_id": "SITE-0106",
      "sku_ids": [
        "SKU-0307",
        "SKU-0530"
      ],
      "sku_names": [
        "Heavy-Duty Belt Medium",
        "Brass Aerator Compact"
      ],
      "pair_id": "rev-0001",
      "pair_role": "revision"
    }
  },
  {
    "case_id": "sc-0043",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Riverside HVAC",
      "contact": "Suresh Rao"
    },
    "entities": {
      "customer_id": "CUST-0052",
      "site_id": "SITE-0082",
      "sku_ids": [
        "SKU-0078",
        "SKU-0342"
      ],
      "sku_names": [
        "Standard Wire Nut 50A",
        "Brass Nipple 1-1/4 in"
      ],
      "pair_id": "rev-0002",
      "pair_role": "original"
    }
  },
  {
    "case_id": "sc-0044",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Riverside HVAC",
      "contact": "Suresh Rao"
    },
    "entities": {
      "customer_id": "CUST-0052",
      "site_id": "SITE-0082",
      "sku_ids": [
        "SKU-0078",
        "SKU-0342",
        "SKU-0274"
      ],
      "sku_names": [
        "Standard Wire Nut 50A",
        "Brass Nipple 1-1/4 in",
        "Copper Cap 1-1/2 in"
      ],
      "pair_id": "rev-0002",
      "pair_role": "revision"
    }
  },
  {
    "case_id": "sc-0045",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Apex Plumbing",
      "contact": "Arjun Gupta"
    },
    "entities": {
      "customer_id": "CUST-0085",
      "site_id": "SITE-0130",
      "sku_ids": [
        "SKU-0479"
      ],
      "sku_names": [
        "Heavy-Duty Belt Small"
      ],
      "pair_id": "rev-0003",
      "pair_role": "original"
    }
  },
  {
    "case_id": "sc-0046",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Apex Plumbing",
      "contact": "Arjun Gupta"
    },
    "entities": {
      "customer_id": "CUST-0085",
      "site_id": "SITE-0130",
      "sku_ids": [
        "SKU-0479",
        "SKU-0428"
      ],
      "sku_names": [
        "Heavy-Duty Belt Small",
        "Heavy-Duty Belt 16x20"
      ],
      "pair_id": "rev-0003",
      "pair_role": "revision"
    }
  },
  {
    "case_id": "sc-0047",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Harbor HVAC",
      "contact": "Arjun Shah"
    },
    "entities": {
      "customer_id": "CUST-0011",
      "site_id": "SITE-0014",
      "sku_ids": [
        "SKU-0301"
      ],
      "sku_names": [
        "PEX Coupling 2-1/2 in"
      ],
      "pair_id": "rev-0004",
      "pair_role": "original"
    }
  },
  {
    "case_id": "sc-0048",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Harbor HVAC",
      "contact": "Arjun Shah"
    },
    "entities": {
      "customer_id": "CUST-0011",
      "site_id": "SITE-0014",
      "sku_ids": [
        "SKU-0301",
        "SKU-0579"
      ],
      "sku_names": [
        "PEX Coupling 2-1/2 in",
        "Residential Furnace 4 Ton"
      ],
      "pair_id": "rev-0004",
      "pair_role": "revision"
    }
  },
  {
    "case_id": "sc-0049",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Titan Group",
      "contact": "Vikram Reddy"
    },
    "entities": {
      "customer_id": "CUST-0005",
      "site_id": "SITE-0007",
      "sku_ids": [
        "SKU-0078",
        "SKU-0544"
      ],
      "sku_names": [
        "Standard Wire Nut 50A",
        "Heavy-Duty Switch 60A"
      ],
      "pair_id": "rev-0005",
      "pair_role": "original"
    }
  },
  {
    "case_id": "sc-0050",
    "scenario_type": "revision_pair",
    "customer": {
      "name": "Titan Group",
      "contact": "Vikram Reddy"
    },
    "entities": {
      "customer_id": "CUST-0005",
      "site_id": "SITE-0007",
      "sku_ids": [
        "SKU-0078",
        "SKU-0544",
        "SKU-0295"
      ],
      "sku_names": [
        "Standard Wire Nut 50A",
        "Heavy-Duty Switch 60A",
        "PVC Coupling 2 in"
      ],
      "pair_id": "rev-0005",
      "pair_role": "revision"
    }
  }
]