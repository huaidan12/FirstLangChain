import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from projects.bookkeeper.nodes import ExpenseItem, chain

# 初始化日志和 FastAPI 应用
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLM-App")
app = FastAPI(title="AI 结构化数据提取服务")


# 前端传入的结构
class ExtractRequest(BaseModel):
    raw_text: str = Field(..., description="需要提取的原始文本描述")


# HTTP 接口（异步）
@app.post("/api/expense/extract", response_model=ExpenseItem)
async def extract_expense(request: ExtractRequest):
    if not request.raw_text.strip():
        raise HTTPException(status_code=400, detail="输入文本不能为空")

    logger.info(f"收到提取请求，原始文本: {request.raw_text}")

    try:
        # ainvoke 是 LangChain 的异步调用方法，不会阻塞 Python 事件循环
        result: ExpenseItem = await chain.ainvoke({"raw_text": request.raw_text})
        logger.info(f"AI 提取成功: {result.model_dump_json()}")
        return result

    except Exception as e:
        # 捕获所有可能的异常（如大模型超时、网络错误、解析失败）
        logger.error(f"AI 提取发生错误: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="大模型服务暂不可用或无法解析该文本，请稍后再试",
        )


# 本地调试可以保留，生产环境通过 uvicorn 启动
if __name__ == "__main__":
    import uvicorn

    # 1. 优先读取 Render 环境分配的端口，如果读取不到（比如在本地），则默认用 8000
    port = int(os.getenv("PORT", 8000))

    # 2. 区分本地开发和生产环境：Render 会注入 PORT，此时关闭 reload
    is_local = os.getenv("PORT") is None

    uvicorn.run(
        "projects.bookkeeper.main:app",
        host="0.0.0.0",
        port=port,
        reload=is_local,
    )
