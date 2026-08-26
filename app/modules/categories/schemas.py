from pydantic import BaseModel, ConfigDict


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    category_id: int
    name: str
    slug: str


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    category_id: int
    name: str
    slug: str
