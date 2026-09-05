"""LLM 入口 — 业务代码只 import 本模块的 chat()，换 SDK/供应商只改这里。

供应商与 bosch-ai-framework 对齐：DashScope OpenAI 兼容模式，默认 qwen3.7-plus。
key 不落本仓库（vault 即 git 仓库）：优先环境变量 DASHSCOPE_API_KEY，
缺失时回读 bosch 项目的 .env（同一台机器上的既有事实来源）。
"""
import os
import re
from functools import lru_cache

from openai import OpenAI

DEFAULT_MODEL = os.environ.get("BOOKLOG_LLM_MODEL", "qwen3.7-plus")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BOSCH_ENV = os.environ.get(
    "BOOKLOG_KEY_SOURCE",
    "/Users/eric/Documents/Scripts/bosch-ai/bosch-ai-framework/.env")


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if key:
        return key
    try:
        m = re.search(r"^DASHSCOPE_API_KEY=(\S+)", open(BOSCH_ENV).read(), re.M)
    except OSError:
        m = None
    if not m:
        raise RuntimeError(f"无 DASHSCOPE_API_KEY：设环境变量或检查 {BOSCH_ENV}")
    return m.group(1)


@lru_cache
def _client() -> OpenAI:
    return OpenAI(base_url=BASE_URL, api_key=_api_key())


def chat(messages: list[dict], model: str | None = None) -> str:
    """同步单次对话（FastAPI 同步路由在线程池里跑，不卡事件循环）。"""
    r = _client().chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=messages,
        extra_body={"enable_thinking": False},
    )
    return r.choices[0].message.content.strip()
