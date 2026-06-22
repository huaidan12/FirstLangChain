from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.workflow import agent_executor

app = FastAPI(title="AI Code Gen Agent Service", version="1.0.0")

# 定义 HTTP 请求和响应的 DTO 契约
class TaskRequest(BaseModel):
    requirement: str

class TaskResponse(BaseModel):
    status: str
    iterations: int
    final_code: str
    error: str

@app.post("/run_task", response_model=TaskResponse)
async def run_agent_task(payload: TaskRequest):
    # 初始化 LangGraph 状态上下文
    initial_state = {
        "requirement": payload.requirement,
        "code": "",
        "error_msg": "",
        "iterations": 0
    }

    try:
        # 同步阻塞唤醒 Agent 工作流
        final_output = agent_executor.invoke(initial_state)

        status = "COMPLETED" if not final_output["error_msg"] else "FAILED"
        return TaskResponse(
            status=status,
            iterations=final_output["iterations"],
            final_code=final_output["code"],
            error=final_output["error_msg"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent runtime error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)