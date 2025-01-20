from pydantic import BaseModel


class MongoSettings(BaseModel):
    MONGO_URI: str
    MONGO_DATABASE: str
