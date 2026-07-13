import os
from fastapi import FastAPI

from projects.bookkeeper.main import app as bookkeeper_app

# ────────────────────────────────────────────────────────────────
# ⚠️ 部署环境适配说明
# ────────────────────────────────────────────────────────────────
# 当前部署目标是 Vercel Serverless，环境是「短生命周期 + 只读文件系统」，
# 只有 /tmp 可写且跨请求会丢。coder 项目依赖：
#   - SqliteSaver（写 data/checkpoint.sqlite）
#   - Milvus Lite（写 data/milvus_demo.db/）
#   - workflow.py 模块导入期就 os.makedirs("data")
# 这些都跟 Serverless 的运行模型不兼容，会直接崩在 import 阶段（Read-only fs）。
#
# 所以这里暂时只挂载 bookkeeper（纯 LLM 调用、无状态、不写盘）。
# 换到长驻托管（Render / Railway / Fly.io / 自建 VM）并挂持久盘之后，
# 把下面两行注释放开即可恢复 coder 服务：
#
from projects.coder.main import app as coder_app
# ────────────────────────────────────────────────────────────────

app = FastAPI(title="AI 多项目聚合入口")

app.mount("/bookkeeper", bookkeeper_app)
app.mount("/coder", coder_app)


@app.get("/")
async def index():
    return {
        "services": {
            "bookkeeper": "/bookkeeper/api/expense/extract",
            "coder": "/coder/run_task",  # 长驻环境部署后放开
        }
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    is_local = os.getenv("PORT") is None
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=is_local)
