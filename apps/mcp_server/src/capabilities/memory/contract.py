from pydantic import BaseModel, Field


class SaveResult(BaseModel):
    id: int = Field(description="Id of the saved (or already existing) note.")
    message: str


class SearchResult(BaseModel):
    count: int = Field(description="Number of notes returned.")
    message: str


class ForgetResult(BaseModel):
    forgotten: bool = Field(description="True when a note was deleted.")
    message: str
