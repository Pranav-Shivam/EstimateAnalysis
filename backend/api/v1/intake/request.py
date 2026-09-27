from pydantic import BaseModel


class IntakeRequest(BaseModel):
    email_text: str
