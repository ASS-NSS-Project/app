from pydantic import BaseModel

# DB examples
class ItemCreate(BaseModel):
    name: str
    description: str

class ItemOut(ItemCreate):
    id: int

    class ConfigDict:
        from_attributes = True

# Example Rag
class RagTextInput(BaseModel):
    text: str

class RagQueryInput(BaseModel):
    query: str

class RagAnswerOutput(BaseModel):
    answer: str