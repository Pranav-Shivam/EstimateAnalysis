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
    "case_id": "sc-0021",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Elite Mechanical",
      "contact": "Devika Rao"
    },
    "entities": {
      "customer_id": "CUST-0074",
      "contract_id": "CTR-0074",
      "covered_categories": [
        "Plumbing-Fittings",
        "Plumbing-Fixtures",
        "HVAC-Equipment"
      ],
      "sku_id": "SKU-0041",
      "sku_name": "Heavy-Duty Conduit 60A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0022",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Vanguard HVAC",
      "contact": "Vikram Patel"
    },
    "entities": {
      "customer_id": "CUST-0084",
      "contract_id": "CTR-0084",
      "covered_categories": [
        "Plumbing-Fittings"
      ],
      "sku_id": "SKU-0239",
      "sku_name": "Heavy-Duty Switch 100A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0023",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Advanced Group",
      "contact": "Nisha Iyer"
    },
    "entities": {
      "customer_id": "CUST-0105",
      "contract_id": "CTR-0105",
      "covered_categories": [
        "HVAC-Parts",
        "Plumbing-Fixtures",
        "Electrical-Supplies"
      ],
      "sku_id": "SKU-0079",
      "sku_name": "High-Efficiency Evaporator Coil 2 Ton",
      "sku_category": "HVAC-Equipment"
    }
  },
  {
    "case_id": "sc-0024",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Metro Co",
      "contact": "Priya Rao"
    },
    "entities": {
      "customer_id": "CUST-0102",
      "contract_id": "CTR-0102",
      "covered_categories": [
        "Plumbing-Fixtures",
        "HVAC-Equipment"
      ],
      "sku_id": "SKU-0274",
      "sku_name": "Copper Cap 1-1/2 in",
      "sku_category": "Plumbing-Fittings"
    }
  },
  {
    "case_id": "sc-0025",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Precision Co",
      "contact": "Anil Shah"
    },
    "entities": {
      "customer_id": "CUST-0120",
      "contract_id": "CTR-0120",
      "covered_categories": [
        "HVAC-Equipment",
        "Electrical-Supplies"
      ],
      "sku_id": "SKU-0156",
      "sku_name": "Stainless Faucet Compact",
      "sku_category": "Plumbing-Fixtures"
    }
  },
  {
    "case_id": "sc-0026",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Coastal Mechanical",
      "contact": "Meera Joshi"
    },
    "entities": {
      "customer_id": "CUST-0032",
      "contract_id": "CTR-0032",
      "covered_categories": [
        "HVAC-Equipment",
        "Plumbing-Fixtures",
        "HVAC-Parts"
      ],
      "sku_id": "SKU-0368",
      "sku_name": "Heavy-Duty Switch 15A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0027",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Highline Services",
      "contact": "Nisha Patel"
    },
    "entities": {
      "customer_id": "CUST-0050",
      "contract_id": "CTR-0050",
      "covered_categories": [
        "HVAC-Parts"
      ],
      "sku_id": "SKU-0358",
      "sku_name": "Heavy-Duty Breaker 50A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0028",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Highline Plumbing",
      "contact": "Ravi Rao"
    },
    "entities": {
      "customer_id": "CUST-0108",
      "contract_id": "CTR-0108",
      "covered_categories": [
        "HVAC-Equipment"
      ],
      "sku_id": "SKU-0368",
      "sku_name": "Heavy-Duty Switch 15A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0029",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Metro Co",
      "contact": "Priya Rao"
    },
    "entities": {
      "customer_id": "CUST-0102",
      "contract_id": "CTR-0102",
      "covered_categories": [
        "Plumbing-Fixtures",
        "HVAC-Equipment"
      ],
      "sku_id": "SKU-0084",
      "sku_name": "Standard Breaker 60A",
      "sku_category": "Electrical-Supplies"
    }
  },
  {
    "case_id": "sc-0030",
    "scenario_type": "discount_category_mismatch",
    "customer": {
      "name": "Metro Mechanical",
      "contact": "Nisha Patel"
    },
    "entities": {
      "customer_id": "CUST-0078",
      "contract_id": "CTR-0078",
      "covered_categories": [
        "HVAC-Parts",
        "Plumbing-Fittings",
        "HVAC-Equipment",
        "Plumbing-Fixtures"
      ],
      "sku_id": "SKU-0557",
      "sku_name": "Heavy-Duty Junction Box 20A",
      "sku_category": "Electrical-Supplies"
    }
  }
]