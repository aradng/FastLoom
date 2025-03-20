from pydantic import BaseModel


class IntrospectionResponse(BaseModel):
    active: bool
