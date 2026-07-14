import os
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from langfuse.callback import CallbackHandler
from projects.coder.workflow import agent_executor

load_dotenv()

app = FastAPI(title="AI Code Gen Agent Service", version="1.0.0")

# Langfuse 配置：项目里已用 LANGFUSE_BASE_URL 命名，
# SDK 官方读的是 LANGFUSE_HOST，故这里显式取值再传参。
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

# 定义 HTTP 请求和响应的 DTO 契约
class TaskRequest(BaseModel):
    requirement: str
    thread_id: Optional[str] = None  # 可选：传入则按该 thread 续跑/回放

class TaskResponse(BaseModel):
    status: str
    iterations: int
    final_code: str
    error: str
    thread_id: str

@app.post("/run_task", response_model=TaskResponse)
async def run_agent_task(payload: TaskRequest):
    # 初始化 LangGraph 状态上下文
    initial_state = {
        "requirement": payload.requirement,
        "code": "",
        "error_msg": "",
        "iterations": 0
    }

    # Checkpointer 按 thread_id 切分会话快照，未指定则随机生成
    thread_id = payload.thread_id or uuid.uuid4().hex

    # 每个请求一个 CallbackHandler：
    #   - session_id 用 thread_id，让多轮续跑挂在同一个 Langfuse Session 下
    #   - tags/metadata 便于在控制台过滤和排障
    langfuse_handler = CallbackHandler(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        host=LANGFUSE_HOST,
        session_id=thread_id,
        tags=["coder-agent"],
        metadata={"requirement": payload.requirement},
    )

    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [langfuse_handler],
    }
    try:
        # 同步阻塞唤醒 Agent 工作流
        final_output = agent_executor.invoke(initial_state, config=config)

        status = "COMPLETED" if not final_output["error_msg"] else "FAILED"
        return TaskResponse(
            status=status,
            iterations=final_output["iterations"],
            final_code=final_output["code"],
            error=final_output["error_msg"],
            thread_id=thread_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent runtime error: {str(e)}")

@app.on_event("shutdown")
def _flush_langfuse():
    # 服务停机前 flush 掉未发送的 event，避免丢日志
    try:
        from langfuse import Langfuse
        Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        ).flush()
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("projects.coder.main:app", host="0.0.0.0", port=8000, reload=True)
