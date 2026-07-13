import os
from fastapi import FastAPI

from projects.bookkeeper.main import app as bookkeeper_app
from projects.coder.main import app as coder_app

app = FastAPI(title="AI 多项目聚合入口")

app.mount("/coder", coder_app)
app.mount("/bookkeeper", bookkeeper_app)


@app.get("/")
async def index():
    return {
        "services": {
            "coder": "/coder/run_task",
            "bookkeeper": "/bookkeeper/api/expense/extract",
        }
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    is_local = os.getenv("PORT") is None
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=is_local)
