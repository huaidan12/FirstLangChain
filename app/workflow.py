from langgraph.graph import StateGraph, END
from app.nodes import AgentState, coder_node, tester_node

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

    # 4. 编译图应用（此处可以外挂 PostgresSaver 作为 checkpointer 实现高可用，本 Demo 暂用内存状态）
    return workflow.compile()

# 暴露单例应用
agent_executor = create_agent_app()