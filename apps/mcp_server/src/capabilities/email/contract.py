from pydantic import BaseModel, Field


class SendResult(BaseModel):
    message_id: str = Field(description="Message-ID to retain for subsequent replies.")
    message: str


class AuditRow(BaseModel):
    time: str
    owner: str
    outcome: str
    recipient_count: int
    message_id: str


class AuditResult(BaseModel):
    deliveries: list[AuditRow]
    message: str
