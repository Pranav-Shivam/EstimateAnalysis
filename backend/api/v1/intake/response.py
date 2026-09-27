import uuid

from pydantic import BaseModel


class LineItemResponse(BaseModel):
    sku_name_as_written: str
    sku_id: str | None
    quantity: str | None


class IntakeResponse(BaseModel):
    quote_request_id: uuid.UUID
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    line_items: list[LineItemResponse]
