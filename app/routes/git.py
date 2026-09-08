"""Git 操作路由。"""
import os
import subprocess

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/git/push")
def git_push(request: Request):
    output, ok = [], True
    env = {**os.environ, "LC_ALL": "C"}
    for command in (["git", "add", "-A"],
                    ["git", "commit", "-m", "book-log: 网页更新"],
                    ["git", "push"]):
        result = subprocess.run(command, cwd=request.app.state.root, capture_output=True,
                                text=True, timeout=120, env=env)
        output.append("$ " + " ".join(command) + "\n" +
                      (result.stdout or "") + (result.stderr or ""))
        ok = ok and result.returncode == 0
    return {"ok": ok, "output": "\n".join(output)}

