from pydantic import BaseModel


class LineItemExtraction(BaseModel):
    sku_name_as_written: str
    quantity: str | None = None


class QuoteRequestExtraction(BaseModel):
    customer_name_as_written: str
    contact_name_as_written: str | None = None
    site_hint: str | None = None
    line_items: list[LineItemExtraction]
    requested_by: str | None = None
    raw_text: str
