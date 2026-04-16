from pydantic import BaseModel, Field, HttpUrl


class MonitoredTourSource(BaseModel):
    internal_code: str = Field(..., min_length=3, max_length=120)
    attraction: str = Field(..., min_length=2, max_length=100)
    variant: str = Field(..., min_length=2, max_length=100)
    source_url: HttpUrl
    external_product_id: str = Field(..., min_length=2, max_length=200)
    city: str = Field(default="Barcelona", max_length=100)
    market: str = Field(default="ES", max_length=10)
