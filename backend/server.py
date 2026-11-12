from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.main import main

app = FastAPI()

# Allow your frontend to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to your frontend URL in production
    allow_methods=["*"],
    allow_headers=["*"],
)

class KeywordRequest(BaseModel):
    keyword: str


@app.post("/suggestions")
def get_suggestions(request: KeywordRequest):

    keyword = request.keyword

    result = main(keyword) #To be Changed

    return result