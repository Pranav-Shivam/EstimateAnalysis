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
    "case_id": "sc-0011",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Sterling Mechanical",
      "contact": "Arjun Gupta"
    },
    "entities": {
      "customer_id": "CUST-0121",
      "sku_id": "SKU-0601",
      "sku_name": "Aftermarket Belt 20x25"
    }
  },
  {
    "case_id": "sc-0012",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Titan Group",
      "contact": "Vikram Reddy"
    },
    "entities": {
      "customer_id": "CUST-0005",
      "sku_id": "SKU-0206",
      "sku_name": "Universal Capacitor 16x20"
    }
  },
  {
    "case_id": "sc-0013",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Highline Services",
      "contact": "Nisha Patel"
    },
    "entities": {
      "customer_id": "CUST-0050",
      "sku_id": "SKU-0156",
      "sku_name": "Stainless Faucet Compact"
    }
  },
  {
    "case_id": "sc-0014",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Bluewater Services",
      "contact": "Nisha Rao"
    },
    "entities": {
      "customer_id": "CUST-0062",
      "sku_id": "SKU-0507",
      "sku_name": "Brass Aerator Deck-Mount"
    }
  },
  {
    "case_id": "sc-0015",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Advanced HVAC",
      "contact": "Kiran Shah"
    },
    "entities": {
      "customer_id": "CUST-0118",
      "sku_id": "SKU-0078",
      "sku_name": "Standard Wire Nut 50A"
    }
  },
  {
    "case_id": "sc-0016",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Ironclad Services",
      "contact": "Meera Shah"
    },
    "entities": {
      "customer_id": "CUST-0025",
      "sku_id": "SKU-0578",
      "sku_name": "PEX Tee 1 in"
    }
  },
  {
    "case_id": "sc-0017",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Cascade Mechanical",
      "contact": "Nisha Reddy"
    },
    "entities": {
      "customer_id": "CUST-0034",
      "sku_id": "SKU-0127",
      "sku_name": "OEM Capacitor 16x20"
    }
  },
  {
    "case_id": "sc-0018",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Ironclad Contractors",
      "contact": "Anil Nair"
    },
    "entities": {
      "customer_id": "CUST-0100",
      "sku_id": "SKU-0290",
      "sku_name": "Residential Furnace 2 Ton"
    }
  },
  {
    "case_id": "sc-0019",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Peak Contractors",
      "contact": "Suresh Gupta"
    },
    "entities": {
      "customer_id": "CUST-0006",
      "sku_id": "SKU-0337",
      "sku_name": "Standard Switch 200A"
    }
  },
  {
    "case_id": "sc-0020",
    "scenario_type": "missing_required_part",
    "customer": {
      "name": "Nexus Co",
      "contact": "Suresh Menon"
    },
    "entities": {
      "customer_id": "CUST-0091",
      "sku_id": "SKU-0146",
      "sku_name": "Residential Compressor 2 Ton"
    }
  }
]