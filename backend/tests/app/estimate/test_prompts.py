import uuid
from types import SimpleNamespace

from app.estimate.prompts import SYSTEM_PROMPT, build_request_message
from tests.app.estimate.seed import AS_OF


def test_request_message_contains_email_resolved_ids_and_date():
    request = SimpleNamespace(
        id=uuid.uuid4(), customer_id="CUST-E1", site_id=None, contract_id="CTR-E1",
        raw_email_text="need 3 widgets", parsed_json={"resolved_line_items": [
            {"sku_name_as_written": "widget", "sku_id": "SKU-E-A1", "quantity": "3"}]},
    )

    message = build_request_message(request, AS_OF)

    assert "need 3 widgets" in message
    assert "CUST-E1" in message
    assert "SKU-E-A1" in message
    assert "2024-09-01" in message


def test_system_prompt_states_the_policy():
    for phrase in ("submit_draft", "get_related_parts", "predict_price", "discount", "flags", "check_contract_coverage",
                   "live_sku_id", "ask_knowledge"):
        assert phrase in SYSTEM_PROMPT
