
from fastapi import FastAPI, HTTPException
from pydantic import Field
import uvicorn
from pydantic import BaseModel

class News(BaseModel):
    id: int
    title: str
    content: str

app = FastAPI()

idx = [1, 2, 3, 4, 5, 6]

# @app.middleware("http")
# async def middleware1(request, call_next):
#     print("中间件1 start")
#     response = await call_next(request)
#     print("中间件1 end")
#     return response

@app.get("/")
async def root():
    return {
        "message": "Hello FastAPI"
    }

@app.get("/news/{id}", response_model=News)
async def get_news(id: int):
    if id not in idx:
        raise HTTPException(status_code=404,detail="Not Found")
    return {
        "id": id,
        "title": f"第 {id} 本书",
        "content": f"第 {id} 本书内容",
    }

if __name__ == '__main__':

    uvicorn.run("demo:app", host="127.0.0.1", port=8003, reload=True)