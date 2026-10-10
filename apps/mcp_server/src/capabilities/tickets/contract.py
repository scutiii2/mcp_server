from pydantic import BaseModel, Field


class CreateResult(BaseModel):
    id: int = Field(description="Ticket id, or 0 when no ticket was filed.")
    duplicate: bool = Field(description="True when an identical open automatic report already existed.")
    message: str


class ListResult(BaseModel):
    count: int = Field(description="Number of tickets returned.")
    message: str


class DetailResult(BaseModel):
    id: int = Field(description="Ticket id, or 0 when it was not found.")
    message: str
