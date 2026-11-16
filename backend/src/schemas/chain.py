from pydantic import BaseModel, Field
class ChainNodeInput(BaseModel):
    key: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=2, max_length=160)
    lag: int = Field(ge=0, le=3)
    threshold: float = Field(ge=0, le=1)
class ChainEdgeInput(BaseModel):
    from_key: str = Field(min_length=1, max_length=40)
    to_key: str = Field(min_length=1, max_length=40)
class ChainInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    nodes: list[ChainNodeInput] = Field(min_length=1, max_length=20)
    edges: list[ChainEdgeInput] = Field(default_factory=list, max_length=80)
