# import os
# from typing import List
# from langchain_openai import OpenAIEmbeddings
# from langchain_core.documents import Document
# from pymilvus import MilvusClient
#
# # 数据落盘目录（Milvus Lite 是单文件嵌入式部署）
# DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
# os.makedirs(DATA_DIR, exist_ok=True)
# MILVUS_URI = os.path.join(DATA_DIR, "milvus_demo.db")
#
# COLLECTION_NAME = "agent_error_cases"
# EMBED_DIM = 1024
#
# # 复用 DashScope 的 OpenAI 兼容端点跑 embedding，避免再引一个模型 SDK
# from projects.coder.nodes import OPENAI_API_KEY, OPENAI_API_BASE
#
# embeddings = OpenAIEmbeddings(
#     model="text-embedding-v3",
#     api_key=OPENAI_API_KEY,
#     base_url=OPENAI_API_BASE,
#     dimensions=EMBED_DIM,
#     # DashScope 兼容端点只接收字符串，不支持 OpenAI 那套本地 tiktoken 切 token-id 后再发的模式
#     check_embedding_ctx_length=False,
# )
#
# # 历史报错-修复经验种子库（Demo 用，生产应从外部数据源同步）
# SEED_CASES: List[Document] = [
#     Document(
#         page_content=(
#             "报错: NameError: name 'xxx' is not defined\n"
#             "诊断: 变量或函数未声明就被使用，常见于忘记 import 或拼写错误。\n"
#             "修复: 检查 import 语句和变量声明顺序，确保 execute() 内引用的符号都已定义。"
#         )
#     ),
#     Document(
#         page_content=(
#             "报错: TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
#             "诊断: 数值与字符串直接拼接导致类型不兼容。\n"
#             "修复: 使用 str() 显式转换，或用 f-string 格式化输出。"
#         )
#     ),
#     Document(
#         page_content=(
#             "报错: IndentationError / SyntaxError: invalid syntax\n"
#             "诊断: 缩进混乱、缺少冒号、括号不匹配。\n"
#             "修复: 用 4 空格统一缩进，检查 def/if/for 行末冒号和括号配对。"
#         )
#     ),
#     Document(
#         page_content=(
#             "报错: ZeroDivisionError: division by zero\n"
#             "诊断: 除数未做边界判断。\n"
#             "修复: 在做除法前判断分母是否为 0，必要时抛出 ValueError 或返回兜底值。"
#         )
#     ),
#     Document(
#         page_content=(
#             "报错: TimeoutError: Code execution exceeded 5 seconds limit\n"
#             "诊断: 出现死循环或低效算法。\n"
#             "修复: 检查 while 循环退出条件，避免 O(n^2) 之上的暴力枚举，必要时用 set/dict 加速查找。"
#         )
#     ),
# ]
#
#
# def _ensure_collection_and_seed(client: MilvusClient) -> None:
#     """首次连接时建表并灌入种子数据；已建表则跳过。"""
#     if client.has_collection(COLLECTION_NAME):
#         return
#
#     print(f"--> [KB] 检测到新 Milvus Lite 库，建表并注入 {len(SEED_CASES)} 条种子案例。")
#     client.create_collection(
#         collection_name=COLLECTION_NAME,
#         dimension=EMBED_DIM,
#         primary_field_name="id",
#         vector_field_name="vector",
#         auto_id=True,
#         enable_dynamic_field=True,  # 让 text 字段以 dynamic field 落库
#     )
#
#     vectors = embeddings.embed_documents([d.page_content for d in SEED_CASES])
#     rows = [{"vector": vec, "text": doc.page_content} for vec, doc in zip(vectors, SEED_CASES)]
#     client.insert(collection_name=COLLECTION_NAME, data=rows)
#
#
# def retrieve_similar_cases(error_msg: str, k: int = 2) -> str:
#     """根据当前报错检索 Top-K 相似的历史案例，拼成可塞进 prompt 的字符串。
#
#     每次调用都新建 MilvusClient：sandbox 的 subprocess.run 会 fork 主进程，
#     污染 pymilvus 全局连接注册表里的复用 alias。每次重建客户端可天然规避这个副作用。
#     """
#     if not error_msg:
#         return ""
#
#     try:
#         client = MilvusClient(uri=MILVUS_URI)
#         _ensure_collection_and_seed(client)
#
#         # 新建的 client 连接老 collection 时默认 released 状态，必须显式 load 才能 search
#         client.load_collection(COLLECTION_NAME)
#
#         query_vec = embeddings.embed_query(error_msg)
#         results = client.search(
#             collection_name=COLLECTION_NAME,
#             data=[query_vec],
#             limit=k,
#             output_fields=["text"],
#         )
#         client.close()
#     except Exception as e:
#         print(f"--> [KB] 检索失败，跳过 RAG 注入: {e}")
#         return ""
#
#     hits = results[0] if results else []
#     if not hits:
#         return ""
#
#     blocks = [f"案例 {idx + 1}:\n{hit.get('entity', {}).get('text', '')}" for idx, hit in enumerate(hits)]
#     return "\n\n".join(blocks)
