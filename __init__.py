# node-smith — ① 우편함 (mailbox)
#
# 하는 일: ComfyUI 서버에 HTTP 라우트 4개를 추가한다.
# 파이썬(MCP서버)과 브라우저(JS)는 서로 직접 통신하지 않고, 이 서버를 우편함처럼 쓴다.
#   - MCP서버가 명령을 POST하면 메모리 큐(pending_commands)에 쌓이고,
#   - 브라우저가 200ms마다 GET으로 꺼내 캔버스에 그린 뒤, 결과를 POST로 반납한다.
#   - 아까 그 POST는 결과가 올 때까지(최대 5초) 기다렸다 돌려준다.
#
# comfy-pilot의 graph_command_handler를 그대로 재현하되, 터미널/자동설치/run-node 등
# v1에 불필요한 부분은 전부 걷어냈다. 캔버스 조작에 필요한 최소 라우트만 남긴다.

import asyncio
import time
import uuid

from aiohttp import web

# ComfyUI가 이 폴더의 js/ 안 파일을 프론트엔드로 자동 로드하게 하는 약속된 변수
WEB_DIRECTORY = "./js"

# 우리는 새 "노드 타입"을 추가하는 게 아니라 HTTP 라우트만 추가하므로 비워 둔다.
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


# ── 우편함 저장소 (서버 메모리에만 존재. 파일도, PC 로컬 자원도 안 씀) ──
pending_commands = []   # MCP서버가 넣고 → 브라우저가 꺼내 가는 "명령 큐"
command_results = {}    # 브라우저가 넣고 → MCP서버가 찾아가는 "결과함" (command_id → result)

# 브라우저가 2초마다 올려주는 현재 캔버스 상태. get_workflow/summarize가 읽는다.
current_workflow = {"workflow": None, "workflow_api": None, "timestamp": None}


async def workflow_handler(request):
    """캔버스 상태 동기화. 브라우저가 POST로 올리고, MCP서버가 GET으로 읽는다."""
    global current_workflow

    if request.method == "POST":
        try:
            data = await request.json()
            current_workflow = {
                "workflow": data.get("workflow"),
                "workflow_api": data.get("workflow_api"),
                "timestamp": data.get("timestamp"),
            }
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    # GET
    return web.json_response(current_workflow)


async def graph_command_handler(request):
    """우편함 본체. 캔버스 조작 명령이 오가는 곳."""
    global pending_commands, command_results

    if request.method == "GET":
        # 브라우저 폴링: 대기 중인 명령이 있으면 하나 꺼내 준다.
        if pending_commands:
            return web.json_response({"command": pending_commands.pop(0)})
        return web.json_response({"command": None})

    # POST — 둘 중 하나:
    #   (a) 브라우저가 실행 결과를 반납  → body에 "result"가 있음
    #   (b) MCP서버가 새 명령을 투입     → body에 "action"이 있음
    try:
        data = await request.json()

        if "result" in data:
            command_results[data.get("command_id")] = data.get("result")
            return web.json_response({"status": "ok"})

        # 새 명령 투입: id를 붙여 큐에 넣고, 브라우저가 결과를 넣어줄 때까지 기다린다.
        cmd_id = str(uuid.uuid4())
        pending_commands.append({
            "id": cmd_id,
            "action": data.get("action"),
            "params": data.get("params", {}),
        })

        start = time.time()
        while cmd_id not in command_results and time.time() - start < 5:
            await asyncio.sleep(0.1)

        if cmd_id in command_results:
            return web.json_response(command_results.pop(cmd_id))
        return web.json_response(
            {"error": "Timeout: 브라우저가 명령을 실행하지 않음 (ComfyUI 탭이 열려 있는지 확인)"},
            status=504,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)


def setup_routes(app):
    app.router.add_get("/node-smith/workflow", workflow_handler)
    app.router.add_post("/node-smith/workflow", workflow_handler)
    app.router.add_get("/node-smith/graph-command", graph_command_handler)
    app.router.add_post("/node-smith/graph-command", graph_command_handler)
    print("[node-smith] 우편함 라우트 등록: /node-smith/workflow, /node-smith/graph-command")


# ComfyUI 서버가 뜰 때 우리 라우트를 끼워 넣는다.
try:
    from server import PromptServer
    setup_routes(PromptServer.instance.app)
    print("[node-smith] 플러그인 로드 완료")
except Exception as e:
    print(f"[node-smith] 라우트 등록 실패: {e}")
    import traceback
    traceback.print_exc()
