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
    "case_id": "sc-0031",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Peak Plumbing",
      "contact": "Priya Shah"
    },
    "entities": {
      "customer_id": "CUST-0015",
      "site_id": "SITE-0020",
      "sku_ids": [
        "SKU-0121",
        "SKU-0243"
      ],
      "sku_names": [
        "Aftermarket Thermostat 16x20",
        "Plastic Drain Wall-Mount"
      ],
      "pair_id": "dup-0001",
      "pair_role": "first"
    }
  },
  {
    "case_id": "sc-0032",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Peak Plumbing",
      "contact": "Nisha Menon"
    },
    "entities": {
      "customer_id": "CUST-0015",
      "site_id": "SITE-0020",
      "sku_ids": [
        "SKU-0121",
        "SKU-0243"
      ],
      "sku_names": [
        "Aftermarket Thermostat 16x20",
        "Plastic Drain Wall-Mount"
      ],
      "pair_id": "dup-0001",
      "pair_role": "second"
    }
  },
  {
    "case_id": "sc-0033",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Apex Co",
      "contact": "Ravi Shah"
    },
    "entities": {
      "customer_id": "CUST-0098",
      "site_id": "SITE-0150",
      "sku_ids": [
        "SKU-0133",
        "SKU-0155"
      ],
      "sku_names": [
        "Brass Tee 1-1/4 in",
        "Universal Filter Large"
      ],
      "pair_id": "dup-0002",
      "pair_role": "first"
    }
  },
  {
    "case_id": "sc-0034",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Apex Co",
      "contact": "Kiran Gupta"
    },
    "entities": {
      "customer_id": "CUST-0098",
      "site_id": "SITE-0150",
      "sku_ids": [
        "SKU-0133",
        "SKU-0155"
      ],
      "sku_names": [
        "Brass Tee 1-1/4 in",
        "Universal Filter Large"
      ],
      "pair_id": "dup-0002",
      "pair_role": "second"
    }
  },
  {
    "case_id": "sc-0035",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Prairie Co",
      "contact": "Devika Kapoor"
    },
    "entities": {
      "customer_id": "CUST-0095",
      "site_id": "SITE-0144",
      "sku_ids": [
        "SKU-0068",
        "SKU-0294"
      ],
      "sku_names": [
        "Universal Capacitor Large",
        "Standard Junction Box 60A"
      ],
      "pair_id": "dup-0003",
      "pair_role": "first"
    }
  },
  {
    "case_id": "sc-0036",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Prairie Co",
      "contact": "Devika Kapoor"
    },
    "entities": {
      "customer_id": "CUST-0095",
      "site_id": "SITE-0144",
      "sku_ids": [
        "SKU-0068",
        "SKU-0294"
      ],
      "sku_names": [
        "Universal Capacitor Large",
        "Standard Junction Box 60A"
      ],
      "pair_id": "dup-0003",
      "pair_role": "second"
    }
  },
  {
    "case_id": "sc-0037",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Highline Mechanical",
      "contact": "Nisha Iyer"
    },
    "entities": {
      "customer_id": "CUST-0056",
      "site_id": "SITE-0090",
      "sku_ids": [
        "SKU-0568"
      ],
      "sku_names": [
        "Galvanized Cap 2-1/2 in"
      ],
      "pair_id": "dup-0004",
      "pair_role": "first"
    }
  },
  {
    "case_id": "sc-0038",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Highline Mechanical",
      "contact": "Nisha Iyer"
    },
    "entities": {
      "customer_id": "CUST-0056",
      "site_id": "SITE-0090",
      "sku_ids": [
        "SKU-0568"
      ],
      "sku_names": [
        "Galvanized Cap 2-1/2 in"
      ],
      "pair_id": "dup-0004",
      "pair_role": "second"
    }
  },
  {
    "case_id": "sc-0039",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Titan Plumbing",
      "contact": "Kiran Shah"
    },
    "entities": {
      "customer_id": "CUST-0036",
      "site_id": "SITE-0055",
      "sku_ids": [
        "SKU-0070",
        "SKU-0555"
      ],
      "sku_names": [
        "GFCI Wire Nut 50A",
        "PVC Tee 2 in"
      ],
      "pair_id": "dup-0005",
      "pair_role": "first"
    }
  },
  {
    "case_id": "sc-0040",
    "scenario_type": "duplicate_pair",
    "customer": {
      "name": "Titan Plumbing",
      "contact": "Priya Nair"
    },
    "entities": {
      "customer_id": "CUST-0036",
      "site_id": "SITE-0055",
      "sku_ids": [
        "SKU-0070",
        "SKU-0555"
      ],
      "sku_names": [
        "GFCI Wire Nut 50A",
        "PVC Tee 2 in"
      ],
      "pair_id": "dup-0005",
      "pair_role": "second"
    }
  }
]