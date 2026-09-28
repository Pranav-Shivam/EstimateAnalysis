from pydantic import BaseModel


class AskResponse(BaseModel):
    route: str
    rule: str
    evidence: dict
