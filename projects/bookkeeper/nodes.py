import os
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser


# AI 提取出来的后端结构（既作为解析目标，也作为 HTTP 响应体）
class ExpenseItem(BaseModel):
    category: str = Field(description="消费品类，例如：餐饮、交通、住宿、设备")
    amount: float = Field(description="消费金额")
    currency: str = Field(description="货币单位，如 CNY, USD")
    date: str = Field(description="消费日期，格式 YYYY-MM-DD，若未提及填 unknown")

OPENAI_API_KEY = "sk-ws-H.EDDEHIL.liKs.MEUCIQCJLVECJEBsBKiKDAVaY_XUR9jwUurnGdLJJUBxvUjSYQIgO8-hqlOOuctEqGHOI4xvCffY"
OPENAI_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 初始化 LLM，生产环境建议使用性价比高的轻量模型
llm = ChatOpenAI(
    model="qwen-omni-turbo",
    temperature=0,        # 提取任务必须为 0，保证结果确定性
    timeout=30,           # 上游卡住时最多等 30 秒
    max_retries=2,        # 网络抖动时自动重试 2 次
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE,
)

parser = PydanticOutputParser(pydantic_object=ExpenseItem)
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个财务报销助手。请从用户的描述中准确提取费用信息。\n{format_instructions}"),
    ("user", "提取以下文本的内容：\n{raw_text}"),
])
prompt_with_instructions = prompt.partial(format_instructions=parser.get_format_instructions())

# 暴露 LCEL 链单例
chain = prompt_with_instructions | llm | parser
