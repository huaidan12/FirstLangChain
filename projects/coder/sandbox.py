# import os
# import subprocess
# import uuid
# from typing import Dict
#
# class CodeSandbox:
#     @staticmethod
#     def execute_code(code_content: str) -> Dict[str, str]:
#         """将生成的代码写入隔离文件，并使用独立子进程安全运行"""
#         # 1. 在本地或临时目录生成一个唯一的文件名
#         file_id = uuid.uuid4().hex
#         filename = f"tmp_{file_id}.py"
#
#         # 2. 注入标准测试桩：追加执行 execute() 函数的代码
#         full_code = code_content + "\n\nif __name__ == '__main__':\n    if 'execute' in globals():\n        execute()\n"
#
#         try:
#             with open(filename, "w", encoding="utf-8") as f:
#                 f.write(full_code)
#
#             # 3. 启动子进程执行代码，设置 5 秒超时防止死循环挂起
#             result = subprocess.run(
#                 ["python3", filename],
#                 capture_output=True,
#                 text=True,
#                 timeout=5
#             )
#
#             if result.returncode == 0:
#                 return {"status": "success", "output": result.stdout, "error": ""}
#             else:
#                 # 聚合标准错误与标准输出
#                 error_msg = result.stderr if result.stderr else result.stdout
#                 return {"status": "failed", "output": result.stdout, "error": error_msg}
#
#         except subprocess.TimeoutExpired:
#             return {"status": "failed", "output": "", "error": "TimeoutError: Code execution exceeded 5 seconds limit."}
#         except Exception as e:
#             return {"status": "failed", "output": "", "error": str(e)}
#         finally:
#             # 4. 无论成功失败，必须清理落盘的临时文件
#             if os.path.exists(filename):
#                 os.remove(filename)