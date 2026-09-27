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
    "case_id": "sc-0001",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Zenith Contractors",
      "contact": "Suresh Iyer"
    },
    "entities": {
      "customer_id": "CUST-0004",
      "sku_id": "SKU-0542",
      "sku_name": "Chrome Sprayer Corner-Mount"
    }
  },
  {
    "case_id": "sc-0002",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Peak Plumbing",
      "contact": "Priya Shah"
    },
    "entities": {
      "customer_id": "CUST-0015",
      "sku_id": "SKU-0355",
      "sku_name": "Chrome Stopper Standard"
    }
  },
  {
    "case_id": "sc-0003",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Union Plumbing",
      "contact": "Anil Joshi"
    },
    "entities": {
      "customer_id": "CUST-0013",
      "sku_id": "SKU-0357",
      "sku_name": "Commercial Compressor 4 Ton"
    }
  },
  {
    "case_id": "sc-0004",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Ironclad Contractors",
      "contact": "Nisha Patel"
    },
    "entities": {
      "customer_id": "CUST-0100",
      "sku_id": "SKU-0430",
      "sku_name": "PVC Bushing 1/2 in"
    }
  },
  {
    "case_id": "sc-0005",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Summit Group",
      "contact": "Devika Shah"
    },
    "entities": {
      "customer_id": "CUST-0089",
      "sku_id": "SKU-0545",
      "sku_name": "Chrome Trap Compact"
    }
  },
  {
    "case_id": "sc-0006",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Summit Group",
      "contact": "Suresh Menon"
    },
    "entities": {
      "customer_id": "CUST-0089",
      "sku_id": "SKU-0083",
      "sku_name": "Copper Adapter 2 in"
    }
  },
  {
    "case_id": "sc-0007",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Nexus Mechanical",
      "contact": "Kiran Nair"
    },
    "entities": {
      "customer_id": "CUST-0049",
      "sku_id": "SKU-0122",
      "sku_name": "Universal Contactor 16x20"
    }
  },
  {
    "case_id": "sc-0008",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Crown HVAC",
      "contact": "Devika Reddy"
    },
    "entities": {
      "customer_id": "CUST-0099",
      "sku_id": "SKU-0236",
      "sku_name": "OEM Thermostat 20x25"
    }
  },
  {
    "case_id": "sc-0009",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Advanced Co",
      "contact": "Nisha Gupta"
    },
    "entities": {
      "customer_id": "CUST-0046",
      "sku_id": "SKU-0137",
      "sku_name": "PVC Adapter 1-1/2 in"
    }
  },
  {
    "case_id": "sc-0010",
    "scenario_type": "discontinued_swap",
    "customer": {
      "name": "Nexus Plumbing",
      "contact": "Arjun Kapoor"
    },
    "entities": {
      "customer_id": "CUST-0044",
      "sku_id": "SKU-0183",
      "sku_name": "Weatherproof Conduit 50A"
    }
  }
]