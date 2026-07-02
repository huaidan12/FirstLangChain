import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

# 1. 初始化日志和 FastAPI 应用
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLM-App")
app = FastAPI(title="AI 结构化数据提取服务")

# 2. 定义输入和输出的数据模型 (Pydantic)
# 前端传入的结构
class ExtractRequest(BaseModel):
    raw_text: str = Field(..., description="需要提取的原始文本描述")

# AI 提取出来的后端结构
class ExpenseItem(BaseModel):
    category: str = Field(description="消费品类，例如：餐饮、交通、住宿、设备")
    amount: float = Field(description="消费金额")
    currency: str = Field(description="货币单位，如 CNY, USD")
    date: str = Field(description="消费日期，格式 YYYY-MM-DD，若未提及填 unknown")

# 3. 初始化 LangChain 核心组件
# 确保生产环境配置了正确的环境变量
llm = ChatOpenAI(
    model="qwen-omni-turbo",  # 生产环境建议用性价比高的轻量模型
    temperature=0,        # 提取任务必须为 0，保证结果确定性
    timeout=30,           # 上游卡住时最多等 30 秒，避免请求一直挂着
    max_retries=2,        # 网络抖动时自动重试 2 次
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE")
)

parser = PydanticOutputParser(pydantic_object=ExpenseItem)
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个财务报销助手。请从用户的描述中准确提取费用信息。\n{format_instructions}"),
    ("user", "提取以下文本的内容：\n{raw_text}")
])
prompt_with_instructions = prompt.partial(format_instructions=parser.get_format_instructions())

# 构建 LCEL 链
chain = prompt_with_instructions | llm | parser


# 4. 编写 HTTP 接口 (使用 async 异步)
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
            detail="大模型服务暂不可用或无法解析该文本，请稍后再试"
        )

# 本地调试可以保留，生产环境通过 uvicorn 启动
if __name__ == "__main__":
    import uvicorn
    import os

    # 1. 优先读取 Render 环境分配的端口，如果读取不到（比如在本地），则默认用 8000
    port = int(os.getenv("PORT", 8000))

    # 2. 区分本地开发和生产环境
    # 如果是在 Render 环境（通常会注入 PORT 变量），关闭 reload
    # 如果是在本地，可以继续开启 reload
    is_local = os.getenv("PORT") is None

    uvicorn.run(
        "projects.bookkeeper.main:app",
        host="0.0.0.0",
        port=port,
        reload=is_local  # 本地开发时为 True，Render 生产环境自动变为 False
    )
