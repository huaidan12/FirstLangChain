import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import redis
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger("redbook")
logging.basicConfig(level=logging.INFO)

DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "5"))

# 逗号分隔的 API Key 列表，Coze 侧配置其中任意一个
_API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

app = FastAPI(title="RedBook Title Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ---------- 懒加载 Redis：冷启动阶段不建立连接，避免 VPC 抖动导致函数起不来 ----------
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT") or 6379),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
    return _redis_client


# ---------- 懒加载 LLM ----------
_llm: Optional[ChatOpenAI] = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-v3"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv(
                "LLM_API_BASE",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            timeout=30,
        )
    return _llm


xiaohongshu_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一个精通小红书爆款文案的营销专家。请根据用户提供的话题，生成5个极具吸引力的标题。\n"
        "要求：\n"
        "1. 必须包含情绪词（如：绝绝子、惊艳、大数据推荐、哭死、谁懂啊）。\n"
        "2. 善用数字和悬念（如：3招搞定、千万别做）。\n"
        "3. 适当加入小红书常用的 Emoji 表情，增加网感。"
    )),
    ("user", "我的话题是：{topic}"),
])


# ---------- 鉴权：Coze 侧填 X-API-Key header ----------
def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not _API_KEYS:
        # 未配置 API_KEYS 环境变量时允许通过，方便本地调试
        return
    if x_api_key not in _API_KEYS:
        raise HTTPException(status_code=401, detail="无效的 API Key")


class TitleRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    topic: str = Field(..., min_length=1, max_length=200)


def _seconds_until_midnight() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate/title", dependencies=[Depends(require_api_key)])
async def generate_title(payload: TitleRequest):
    r = get_redis()
    redis_key = f"user:{payload.user_id}:count"

    try:
        new_count = r.incr(redis_key)
        if new_count == 1:
            r.expire(redis_key, _seconds_until_midnight())
    except redis.RedisError:
        logger.exception("Redis 不可用")
        raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试")

    if new_count > DAILY_LIMIT:
        try:
            r.decr(redis_key)
        except redis.RedisError:
            pass
        raise HTTPException(status_code=403, detail="今日免费额度已用尽，明天再来吧！")

    try:
        response = await (xiaohongshu_prompt | get_llm()).ainvoke({"topic": payload.topic})
    except Exception:
        logger.exception("LLM 调用失败 user_id=%s", payload.user_id)
        try:
            if new_count == 1:
                r.delete(redis_key)
            else:
                r.decr(redis_key)
        except redis.RedisError:
            pass
        raise HTTPException(status_code=502, detail="AI 服务暂不可用，请稍后重试")

    return {
        "code": 200,
        "data": response.content,
        "remaining_count": max(0, DAILY_LIMIT - new_count),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("CA_PORT") or os.getenv("PORT") or 8000)
    uvicorn.run(app, host="0.0.0.0", port=port)
