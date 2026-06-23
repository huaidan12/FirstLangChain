import os
import sqlite3
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from app.nodes import AgentState, coder_node, tester_node

# Checkpointer 落盘位置
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
CHECKPOINT_DB = os.path.join(DATA_DIR, "checkpoint.sqlite")


def decide_next_step(state: AgentState) -> str:
    """条件路由函数：控制流的‘看门狗’"""
    if not state['error_msg']:
        print("--> [Router] 校验通过，准备安全退出工作流。")
        return "success"

    if state['iterations'] >= 3:
        print("--> [Router] 达到最大重试阈值(3次)，强制中止。")
        return "failed"

    print("--> [Router] 检测到代码缺陷，重新路由回 Coder 节点修复。")
    return "retry"

def create_agent_app():
    """构建并编译有向图状态机"""
    workflow = StateGraph(AgentState)

    # 1. 注册节点
    workflow.add_node("coder", coder_node)
    workflow.add_node("tester", tester_node)

    # 2. 设置入口
    workflow.set_entry_point("coder")

    # 3. 建立连线
    workflow.add_edge("coder", "tester")
    workflow.add_conditional_edges(
        "tester",
        decide_next_step,
        {
            "success": END,
            "retry": "coder",
            "failed": END
        }
    )

    # 4. 编译图应用，挂载 SqliteSaver 做轻量 Checkpointer：
    #    - 持久化每一步的图状态，支持按 thread_id 续跑/回放
    #    - check_same_thread=False 是为了让 FastAPI 多线程下也能复用同一连接
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return workflow.compile(checkpointer=checkpointer)

# 暴露单例应用
agent_executor = create_agent_app()
