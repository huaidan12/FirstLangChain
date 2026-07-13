# import uuid
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from projects.coder.workflow import agent_executor
#
# app = FastAPI(title="AI Code Gen Agent Service", version="1.0.0")
#
# # 定义 HTTP 请求和响应的 DTO 契约
# class TaskRequest(BaseModel):
#     requirement: str
#     thread_id: str | None = None  # 可选：传入则按该 thread 续跑/回放
#
# class TaskResponse(BaseModel):
#     status: str
#     iterations: int
#     final_code: str
#     error: str
#     thread_id: str
#
# @app.post("/run_task", response_model=TaskResponse)
# async def run_agent_task(payload: TaskRequest):
#     # 初始化 LangGraph 状态上下文
#     initial_state = {
#         "requirement": payload.requirement,
#         "code": "",
#         "error_msg": "",
#         "iterations": 0
#     }
#
#     # Checkpointer 按 thread_id 切分会话快照，未指定则随机生成
#     thread_id = payload.thread_id or uuid.uuid4().hex
#     config = {"configurable": {"thread_id": thread_id}}
#     try:
#         # 同步阻塞唤醒 Agent 工作流
#         final_output = agent_executor.invoke(initial_state, config=config)
#
#         status = "COMPLETED" if not final_output["error_msg"] else "FAILED"
#         return TaskResponse(
#             status=status,
#             iterations=final_output["iterations"],
#             final_code=final_output["code"],
#             error=final_output["error_msg"],
#             thread_id=thread_id,
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Agent runtime error: {str(e)}")
#
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("projects.coder.main:app", host="0.0.0.0", port=8000, reload=True)
