import re
from typing import Dict, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from projects.coder.sandbox import CodeSandbox


def extract_python_code(raw: str) -> str:
    """从 LLM 输出里抠出纯 Python 代码：优先匹配 fenced block，否则回退到原文。"""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw.strip()

# 本地调试用常量，生产请替换为环境变量
OPENAI_API_KEY = "sk-ws-H.RPHHXMY.lkZo.MEQCIE-XRm1YtDEXK67dfqax-"
OPENAI_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 定义全局状态机的数据契约
class AgentState(TypedDict):
    requirement: str
    code: str
    error_msg: str
    iterations: int

# 初始化 LLM，生产环境建议使用基座大模型（如 gpt-4o 或 Claude 3.5）
llm = ChatOpenAI(
    model="qwen-omni-turbo",
    temperature=0.1,
    timeout=30,
    max_retries=2,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE,
)

def coder_node(state: AgentState) -> Dict:
    """大模型代码生成/修复节点"""
    print(f"--> [Node] Coder 开始第 {state['iterations'] + 1} 次代码编排...")

    if state['error_msg']:
        # 从 Milvus Lite 拉取相似的历史报错案例做 RAG 注入
        # 延迟导入：避免 nodes.py 与 knowledge_base.py 循环依赖
        from projects.coder.knowledge_base import retrieve_similar_cases
        rag_context = retrieve_similar_cases(state['error_msg'], k=2)
        if rag_context:
            print(f"--> [Node] Coder 注入 RAG 上下文，命中 {rag_context.count('案例')} 条相似案例。")

        # 带有错误上下文的修复提示词
        prompt = ChatPromptTemplate.from_template(
            "你是一个精通 Python 的资深架构师。\n"
            "用户原始需求: {requirement}\n\n"
            "你之前生成的代码运行失败了:\n```python\n{code}\n```\n\n"
            "执行单测时的报错信息如下:\n{error_msg}\n\n"
            "知识库中检索到的相似历史案例（仅供参考，可能与当前问题无关）:\n{rag_context}\n\n"
            "请分析原因并修复它。注意：只输出可以直接运行的纯 Python 代码，绝对不要包含 ```python 等 Markdown 标记，必须包含 execute() 函数作为入口。"
        )
        inputs = prompt.format_messages(
            requirement=state['requirement'],
            code=state['code'],
            error_msg=state['error_msg'],
            rag_context=rag_context or "（无）",
        )
    else:
        # 初次生成提示词
        prompt = ChatPromptTemplate.from_template(
            "你是一个精通 Python 的资深架构师。\n"
            "请根据以下需求编写一段健壮的 Python 代码，必须包含一个名为 `execute` 的函数作为业务入口。\n"
            "需求: {requirement}\n\n"
            "注意：只输出可以直接运行的纯 Python 代码，绝对不要包含 ```python 等 Markdown 标记。"
        )
        inputs = prompt.format_messages(requirement=state['requirement'])

    response = llm.invoke(inputs)
    return {
        "code": extract_python_code(response.content),
        "iterations": state['iterations'] + 1
    }

def tester_node(state: AgentState) -> Dict:
    """自动化测试校验节点"""
    print("--> [Node] Tester 接收到快照代码，投递沙箱运行...")

    # 调用安全沙箱层
    sandbox_result = CodeSandbox.execute_code(state['code'])

    if sandbox_result["status"] == "success":
        return {"error_msg": ""}
    else:
        return {"error_msg": sandbox_result["error"]}