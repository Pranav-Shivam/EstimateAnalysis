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
    "case_id": "sc-0051",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Sterling Mechanical",
      "contact": "Arjun Gupta"
    },
    "entities": {
      "customer_id": "CUST-0121",
      "sku_ids": [
        "SKU-0271",
        "SKU-0143"
      ],
      "sku_names": [
        "Brass Union 2-1/2 in",
        "Matte Black Sprayer Wall-Mount"
      ]
    }
  },
  {
    "case_id": "sc-0052",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Union Group",
      "contact": "Anil Joshi"
    },
    "entities": {
      "customer_id": "CUST-0119",
      "sku_ids": [
        "SKU-0396",
        "SKU-0572",
        "SKU-0121"
      ],
      "sku_names": [
        "PVC Cap 2-1/2 in",
        "GFCI Junction Box 60A",
        "Aftermarket Thermostat 16x20"
      ]
    }
  },
  {
    "case_id": "sc-0053",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Total Mechanical",
      "contact": "Devika Rao"
    },
    "entities": {
      "customer_id": "CUST-0124",
      "sku_ids": [
        "SKU-0535",
        "SKU-0157"
      ],
      "sku_names": [
        "PVC Nipple 1-1/2 in",
        "Weatherproof Switch 15A"
      ]
    }
  },
  {
    "case_id": "sc-0054",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Harbor HVAC",
      "contact": "Arjun Shah"
    },
    "entities": {
      "customer_id": "CUST-0011",
      "sku_ids": [
        "SKU-0437",
        "SKU-0414"
      ],
      "sku_names": [
        "Standard Breaker 20A",
        "OEM Gasket Medium"
      ]
    }
  },
  {
    "case_id": "sc-0055",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Total Services",
      "contact": "Meera Shah"
    },
    "entities": {
      "customer_id": "CUST-0029",
      "sku_ids": [
        "SKU-0170"
      ],
      "sku_names": [
        "Copper Coupling 1-1/4 in"
      ]
    }
  },
  {
    "case_id": "sc-0056",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Summit Plumbing",
      "contact": "Arjun Joshi"
    },
    "entities": {
      "customer_id": "CUST-0019",
      "sku_ids": [
        "SKU-0007",
        "SKU-0360",
        "SKU-0335"
      ],
      "sku_names": [
        "Chrome Shutoff Corner-Mount",
        "Universal Capacitor Small",
        "PVC Adapter 1 in"
      ]
    }
  },
  {
    "case_id": "sc-0057",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Elite Plumbing",
      "contact": "Vikram Shah"
    },
    "entities": {
      "customer_id": "CUST-0069",
      "sku_ids": [
        "SKU-0228",
        "SKU-0141",
        "SKU-0180"
      ],
      "sku_names": [
        "Galvanized Union 1 in",
        "Copper Union 2 in",
        "OEM Belt Large"
      ]
    }
  },
  {
    "case_id": "sc-0058",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Ironclad Plumbing",
      "contact": "Suresh Nair"
    },
    "entities": {
      "customer_id": "CUST-0070",
      "sku_ids": [
        "SKU-0084"
      ],
      "sku_names": [
        "Standard Breaker 60A"
      ]
    }
  },
  {
    "case_id": "sc-0059",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Union Plumbing",
      "contact": "Anil Joshi"
    },
    "entities": {
      "customer_id": "CUST-0013",
      "sku_ids": [
        "SKU-0578",
        "SKU-0540"
      ],
      "sku_names": [
        "PEX Tee 1 in",
        "Chrome Sprayer Compact"
      ]
    }
  },
  {
    "case_id": "sc-0060",
    "scenario_type": "clean_distinct",
    "customer": {
      "name": "Metro Plumbing",
      "contact": "Devika Joshi"
    },
    "entities": {
      "customer_id": "CUST-0082",
      "sku_ids": [
        "SKU-0437",
        "SKU-0140"
      ],
      "sku_names": [
        "Standard Breaker 20A",
        "Chrome Shutoff Compact"
      ]
    }
  }
]