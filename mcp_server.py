# -*- coding: utf-8 -*-
# node-smith — ③ 명령관 (MCP 서버)
#
# Claude(에이전트)가 부르는 도구를 우편함(ComfyUI의 /node-smith/* 라우트)에 HTTP로 전달한다.
# 프레임워크 없이 손으로 짠 JSON-RPC(stdio): main()이 stdin을 한 줄씩 읽어 handle_request가
# initialize / tools/list / tools/call 로 분기하고, send_response가 stdout에 한 줄 JSON을 쓴다.
#
# comfy-pilot mcp_server.py를 재구현하되, v1에 필요한 도구 8개만 남기고
# 연결 방식은 COMFYUI_URL 설정값 우선으로 바꿔 단일 PC에서도, 원격에서도 돌게 했다.

import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


# ── ComfyUI 주소 결정 ─────────────────────────────────────────────
# 우선순위: ① COMFYUI_URL 환경변수(명시적 설정) → ② 플러그인이 남긴 .comfyui_url 파일
# (단일 PC 자동감지) → ③ 기본값 127.0.0.1:8188. 이 한 곳 덕분에 맥에서 원격 PC를 가리킬 수도,
# 같은 PC에서 그냥 돌릴 수도 있다. (comfy-pilot이 PC 로컬 파일에만 의존하던 지점을 대체)
def get_comfyui_url() -> str:
    env_url = os.environ.get("COMFYUI_URL")
    if env_url:
        return env_url.rstrip("/")

    url_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".comfyui_url")
    if os.path.exists(url_file):
        try:
            with open(url_file, "r") as f:
                url = f.read().strip()
                if url:
                    return url.rstrip("/")
        except Exception:
            pass

    return "http://127.0.0.1:8188"


COMFYUI_URL = None  # 첫 요청 때 한 번 결정


def make_request(endpoint: str, method: str = "GET", data: dict = None, timeout: int = None) -> dict:
    """ComfyUI HTTP API 호출. 실패는 예외로 던지지 않고 {'error': ...}로 반환한다."""
    global COMFYUI_URL
    if COMFYUI_URL is None:
        COMFYUI_URL = get_comfyui_url()

    url = f"{COMFYUI_URL}{endpoint}"
    if timeout is None:
        timeout = 30 if endpoint == "/object_info" else 10

    try:
        if data is not None:
            req = urllib.request.Request(
                url,
                data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method=method,
            )
        else:
            req = urllib.request.Request(url, method=method)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code} {e.reason} from ComfyUI"}
    except urllib.error.URLError as e:
        return {"error": f"ComfyUI 연결 실패({COMFYUI_URL}): {e.reason}"}
    except socket.timeout:
        return {"error": f"ComfyUI 응답 없음 ({timeout}s 초과)"}
    except json.JSONDecodeError:
        return {"error": "ComfyUI가 JSON이 아닌 응답을 보냄"}
    except Exception as e:
        return {"error": f"예상치 못한 오류: {type(e).__name__}: {e}"}


# object_info(노드 사전)는 잘 안 바뀌므로 5분 캐시
_object_info_cache = None
_object_info_cache_time = 0
CACHE_TTL = 300


def get_object_info_cached() -> dict:
    global _object_info_cache, _object_info_cache_time
    now = time.time()
    if _object_info_cache is not None and now - _object_info_cache_time < CACHE_TTL:
        return _object_info_cache
    result = make_request("/object_info")
    if "error" not in result:
        _object_info_cache = result
        _object_info_cache_time = now
    return result


def send_graph_command(action: str, params: dict) -> dict:
    """캔버스 조작 명령을 우편함에 POST한다. 브라우저가 실행하고 결과를 돌려줄 때까지 서버가 대기."""
    return make_request(
        "/node-smith/graph-command",
        method="POST",
        data={"action": action, "params": params},
    )


def get_workflow() -> dict:
    """브라우저가 우편함에 올려둔 현재 캔버스 상태를 읽는다."""
    live = make_request("/node-smith/workflow")
    if live and live.get("workflow"):
        return {"source": "live", "workflow": live.get("workflow"), "timestamp": live.get("timestamp")}
    return {"message": "캔버스를 읽을 수 없음. ComfyUI 탭이 열려 있고 node-smith가 로드됐는지 확인."}


def get_history(prompt_id: str = None) -> dict:
    return make_request(f"/history/{prompt_id}" if prompt_id else "/history")


# ── 도구: 노드 사전 조회 ──────────────────────────────────────────
def _format_type_io(node_info: dict, fields: list) -> list:
    """노드 하나의 입력/출력 타입을 축약 표기로."""
    lines = []
    if "input_types" in fields or "inputs" in fields:
        inputs = []
        for group in ("required", "optional"):
            for name, definition in node_info.get("input", {}).get(group, {}).items():
                if isinstance(definition, list) and definition:
                    t = definition[0] if isinstance(definition[0], str) else type(definition[0]).__name__
                    inputs.append(f"{name}{'*' if group == 'required' else ''}:{t}")
        if inputs:
            lines.append(f"    in: {','.join(inputs)}")
    if "output_types" in fields or "outputs" in fields:
        outputs = node_info.get("output", [])
        names = node_info.get("output_name", outputs)
        if outputs:
            parts = [f"{names[i] if i < len(names) else t}:{t}" for i, t in enumerate(outputs)]
            lines.append(f"    out: {','.join(parts)}")
    return lines


def get_node_types(search=None, category: str = None, fields: list = None) -> str:
    """설치된 노드 타입 검색. 축약(TOON) 포맷으로 반환. 필터 없으면 카테고리 요약만."""
    all_nodes = get_object_info_cached()
    if "error" in all_nodes:
        return f"error: {all_nodes['error']}"
    fields = fields or []

    def format_node(name, info):
        display = (info.get("display_name") or name).replace(",", ";")
        cat = (info.get("category") or "uncategorized").replace(",", ";")
        head = f"  {name},{display},{cat}"
        if "description" in fields:
            head += "," + (info.get("description") or "").replace("\n", " ").replace(",", ";")[:100]
        return [head] + _format_type_io(info, fields)

    # 필터 없음 → 카테고리별 개수 요약 (통째 반환 금지, 토큰 절약)
    if not search and not category:
        cats = {}
        for name, info in all_nodes.items():
            cats.setdefault(info.get("category", "uncategorized"), []).append(name)
        lines = [f"total: {len(all_nodes)} nodes", f"categories[{len(cats)}]{{name,count}}:"]
        lines += [f"  {c},{len(cats[c])}" for c in sorted(cats)]
        lines.append("hint: 'search' 또는 'category'로 좁혀 조회")
        return "\n".join(lines)

    if search:
        terms = search if isinstance(search, list) else [search]
        lines = []
        for term in terms:
            tl = term.lower()
            matches = [(n, i) for n, i in all_nodes.items()
                       if tl in n.lower()
                       or tl in (i.get("display_name") or "").lower()
                       or tl in (i.get("description") or "").lower()]
            lines.append(f'search "{term}": {len(matches)} matches')
            if matches:
                lines.append(f"nodes[{len(matches)}]{{name,display,category}}:")
                for n, i in sorted(matches, key=lambda x: x[0]):
                    lines += format_node(n, i)
        return "\n".join(lines)

    cl = category.lower()
    matches = [(n, i) for n, i in all_nodes.items() if cl in (i.get("category") or "").lower()]
    lines = [f'category "{category}": {len(matches)} matches']
    if matches:
        lines.append(f"nodes[{len(matches)}]{{name,display,category}}:")
        for n, i in sorted(matches, key=lambda x: x[0]):
            lines += format_node(n, i)
    return "\n".join(lines)


def get_node_info(node_id: str) -> str:
    """캔버스의 특정 노드 상세: 타입·위치·입출력·연결·위젯값. 축약 포맷."""
    wf = get_workflow()
    if "error" in wf or "message" in wf:
        return f"error: {wf.get('error') or wf.get('message')}"
    workflow = wf.get("workflow", {})
    try:
        nid = int(node_id)
    except (ValueError, TypeError):
        return f"error: invalid node_id '{node_id}'"

    for node in workflow.get("nodes", []):
        if node.get("id") != nid:
            continue
        node_type = node.get("type")
        pos = node.get("pos", [0, 0])
        size = node.get("size", [200, 100])
        x, y = (pos.get("0", 0), pos.get("1", 0)) if isinstance(pos, dict) else (pos[0], pos[1])
        w, h = (size.get("0", 200), size.get("1", 100)) if isinstance(size, dict) else (size[0], size[1])

        lines = [f"node {nid}: {node.get('title') or node_type}",
                 f"type: {node_type}",
                 f"pos: {round(x)},{round(y)} size: {round(w)}x{round(h)}"]

        info = get_object_info_cached().get(node_type, {})
        if info:
            if info.get("category"):
                lines.append(f"category: {info['category']}")
            lines += _format_type_io(info, ["inputs", "outputs"])

        for inp in node.get("inputs", []) or []:
            if isinstance(inp, dict) and inp.get("link"):
                lines.append(f"input {inp.get('name', '?')} <- link{inp['link']}")
        widgets = node.get("widgets_values")
        if widgets:
            vals = [(str(v)[:47] + "..." if len(str(v)) > 50 else str(v)).replace(",", ";").replace("\n", "\\n")
                    for v in widgets]
            lines.append(f"widgets[{len(widgets)}]: {','.join(vals)}")
        return "\n".join(lines)

    return f"error: node {node_id} not found in workflow"


def summarize_workflow() -> str:
    """현재 캔버스 요약(TOON): 캔버스 범위 + 노드목록(id,type,title,x,y,w,h) + 연결목록."""
    wf = get_workflow()
    if "error" in wf or "message" in wf:
        return f"error: {wf.get('error') or wf.get('message')}"
    workflow = wf.get("workflow", {})
    if "nodes" not in workflow:
        return "error: 캔버스에 노드가 없음"

    nodes = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for node in workflow.get("nodes", []):
        pos = node.get("pos", [0, 0])
        size = node.get("size", [200, 100])
        x, y = (pos.get("0", 0), pos.get("1", 0)) if isinstance(pos, dict) else (pos[0], pos[1])
        w, h = (size.get("0", 200), size.get("1", 100)) if isinstance(size, dict) else (size[0], size[1])
        x, y, w, h = round(x), round(y), round(w), round(h)
        min_x, min_y, max_x, max_y = min(min_x, x), min(min_y, y), max(max_x, x + w), max(max_y, y + h)
        nodes.append({
            "id": node.get("id"),
            "type": (node.get("type") or "").replace(",", ";"),
            "title": (node.get("title") or "").replace(",", ";"),
            "x": x, "y": y, "w": w, "h": h,
        })
    nodes.sort(key=lambda n: int(n["id"]) if str(n["id"]).isdigit() else 0)

    lines = []
    if nodes:
        lines.append(f"canvas: {round(min_x)},{round(min_y)} to {round(max_x)},{round(max_y)}")
    lines.append(f"nodes[{len(nodes)}]{{id,type,title,x,y,w,h}}:")
    for n in nodes:
        lines.append(f"  {n['id']},{n['type']},{n['title']},{n['x']},{n['y']},{n['w']},{n['h']}")

    links = workflow.get("links", [])
    if links:
        lines.append(f"connections[{len(links)}]{{from:slot->to:slot,type}}:")
        for link in links:
            if len(link) >= 6:  # [link_id, from_node, from_slot, to_node, to_slot, type]
                lines.append(f"  {link[1]}:{link[2]}->{link[3]}:{link[4]},{link[5]}")
    return "\n".join(lines)


# ── 도구: 실행 ────────────────────────────────────────────────────
def run(action: str = "queue", node_ids=None) -> dict:
    """워크플로우를 큐에 올려 실행하거나 중단한다."""
    if action == "interrupt":
        return make_request("/interrupt", method="POST")
    if action == "queue":
        # 브라우저에서 큐에 올려야 client_id가 맞아 미리보기가 UI에 뜬다
        result = send_graph_command("queue_prompt", {})
        if "error" in result:
            return result
        return {"status": "queued"}
    return {"error": f"Unknown action: {action}. 'queue' 또는 'interrupt'."}


# ── 도구: 캔버스 편집 (간판 기능) ─────────────────────────────────
# operations 리스트를 순서대로 우편함에 흘려보낸다. create가 돌려준 node_id를 'ref'로
# 다음 연산에서 참조할 수 있어, 한 번의 호출로 "노드 여럿 생성 + 서로 연결"이 가능하다.
def edit_graph(operations) -> str:
    if isinstance(operations, str):
        try:
            operations = json.loads(operations)
        except json.JSONDecodeError:
            return "error: operations는 JSON 객체 또는 배열이어야 함"
    if isinstance(operations, dict):
        operations = [operations]
    if not isinstance(operations, list):
        return "error: operations는 JSON 객체 또는 배열이어야 함"

    all_nodes = get_object_info_cached()
    if "error" in all_nodes:
        return f"error: {all_nodes['error']}"

    results = []
    refs = {}  # ref 이름 → 실제 node_id
    viewport_offset = 0  # place_in_view 노드를 나란히 놓기 위한 가로 오프셋

    def resolve(nid):
        return refs.get(nid, nid)

    for i, op in enumerate(operations):
        action = op.get("action", "")
        r = {"action": action, "index": i}
        try:
            if action == "create":
                node_type = op.get("node_type", "")
                if not node_type:
                    r["error"] = "node_type이 필요함"
                elif node_type not in all_nodes:
                    r["error"] = f"모르는 노드 타입: {node_type}"
                else:
                    place_in_view = op.get("place_in_view", False)
                    out = send_graph_command("create_node", {
                        "type": node_type,
                        "pos_x": op.get("pos_x", 100),
                        "pos_y": op.get("pos_y", 100),
                        "title": op.get("title"),
                        "place_in_view": place_in_view,
                        "viewport_offset": viewport_offset if place_in_view else 0,
                    })
                    r.update(out)
                    if "node_id" in out and op.get("ref"):
                        refs[op["ref"]] = out["node_id"]
                    if place_in_view and "node_id" in out:
                        viewport_offset += 330  # 노드 폭 + 여백만큼 다음 노드를 오른쪽으로

            elif action == "delete":
                for nid in op.get("node_ids") or [op.get("node_id")]:
                    if nid:
                        r.update(send_graph_command("delete_node", {"node_id": str(resolve(nid))}))

            elif action == "move":
                nid = op.get("node_id", "")
                if not nid:
                    r["error"] = "node_id가 필요함"
                else:
                    rel = op.get("relative_to")
                    r.update(send_graph_command("move_node", {
                        "node_id": str(resolve(nid)),
                        "x": op.get("x"), "y": op.get("y"),
                        "relative_to": str(resolve(rel)) if rel else None,
                        "direction": op.get("direction"),
                        "gap": op.get("gap", 30),
                    }))

            elif action == "resize":
                nid = op.get("node_id", "")
                if not nid:
                    r["error"] = "node_id가 필요함"
                else:
                    r.update(send_graph_command("move_node", {
                        "node_id": str(resolve(nid)),
                        "width": op.get("width"), "height": op.get("height"),
                    }))

            elif action == "set":
                nid = op.get("node_id", "")
                if not nid:
                    r["error"] = "node_id가 필요함"
                else:
                    props = dict(op.get("properties", {}))
                    if "property" in op:
                        props[op["property"]] = op.get("value")
                    for name, value in props.items():
                        r.update(send_graph_command("set_node_property", {
                            "node_id": str(resolve(nid)), "property_name": name, "value": value,
                        }))

            elif action in ("connect", "disconnect"):
                fr, to = op.get("from_node", ""), op.get("to_node", "")
                if not fr or not to:
                    r["error"] = "from_node와 to_node가 필요함"
                else:
                    r.update(send_graph_command(f"{action}_nodes", {
                        "from_node_id": str(resolve(fr)), "from_slot": op.get("from_slot", 0),
                        "to_node_id": str(resolve(to)), "to_slot": op.get("to_slot", 0),
                    }))
            else:
                r["error"] = f"모르는 action: {action}"
        except Exception as e:
            r["error"] = str(e)
        results.append(r)

    # 축약 결과: 성공/실패 개수 + 생성된 id + 에러만
    failed = [r for r in results if "error" in r]
    lines = [f"{'failed' if failed else 'ok'}: {len(results) - len(failed)}/{len(results)}"]
    created = [str(r["node_id"]) for r in results if r.get("action") == "create" and "node_id" in r]
    if created:
        lines.append(f"created: {','.join(created)}")
    if failed:
        lines.append("errors:")
        for r in failed:
            lines.append(f"  [{r['index']}] {r['action']}: {r['error']}")
    return "\n".join(lines)


def center_on_node(node_id: str) -> str:
    """사용자 화면을 특정 노드로 스크롤(생성 후 어디 놓였는지 보여줄 때)."""
    result = send_graph_command("center_on_node", {"node_id": str(node_id)})
    if "error" in result:
        return f"error: {result['error']}"
    return f"ok: centered on node {node_id}"


# ── 도구: 결과 이미지 보기 ────────────────────────────────────────
def view_image(node_id: str = None, image_index: int = 0) -> dict:
    """Preview/Save Image 노드의 최신 출력 이미지를 base64로 가져와 대화창에 표시."""
    wf = get_workflow()
    if "error" in wf or "message" in wf:
        return {"error": wf.get("error") or wf.get("message")}
    workflow = wf.get("workflow", {})

    image_nodes = [
        {"id": n.get("id"), "type": n.get("type", ""), "title": n.get("title") or n.get("type")}
        for n in workflow.get("nodes", [])
        if any(t in n.get("type", "").lower() for t in ("preview", "saveimage", "save image"))
    ]
    if not image_nodes:
        return {"error": "캔버스에 Preview/Save Image 노드가 없음"}

    if node_id:
        target = next((n for n in image_nodes if n["id"] == int(node_id)), None)
        if not target:
            return {"error": f"node {node_id}는 이미지 노드가 아님", "available_image_nodes": image_nodes}
    else:
        target = image_nodes[0]

    history = get_history()
    if "error" in history:
        return {"error": "히스토리를 못 읽음. 먼저 run으로 워크플로우를 실행하세요."}

    # 가장 최근 실행부터 이 노드의 출력 이미지를 찾는다
    items = []
    for pid, pdata in history.items():
        if not isinstance(pdata, dict):
            continue
        ts = 0
        for msg in pdata.get("status", {}).get("messages", []):
            if len(msg) >= 2 and isinstance(msg[1], dict):
                ts = max(ts, msg[1].get("timestamp", 0))
        items.append((pdata, ts))
    items.sort(key=lambda x: x[1], reverse=True)

    image_info = None
    tid = str(target["id"])
    for pdata, _ in items:
        imgs = pdata.get("outputs", {}).get(tid, {}).get("images", [])
        if imgs and len(imgs) > image_index:
            image_info = imgs[image_index]
            break
    if not image_info:
        return {"error": f"node {target['id']}의 이미지 없음. 먼저 실행하세요.", "node": target}

    params = f"filename={urllib.parse.quote(image_info.get('filename', ''))}&type={image_info.get('type', 'output')}"
    if image_info.get("subfolder"):
        params += f"&subfolder={urllib.parse.quote(image_info['subfolder'])}"

    try:
        req = urllib.request.Request(f"{get_comfyui_url()}/view?{params}", method="GET")
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            ctype = response.headers.get("Content-Type", "image/png")
        media = "image/jpeg" if "jpeg" in ctype or "jpg" in ctype else ("image/webp" if "webp" in ctype else "image/png")
        return {
            "node_id": target["id"], "node_title": target["title"],
            "filename": image_info.get("filename", ""),
            "media_type": media,
            "base64_data": base64.b64encode(data).decode("utf-8"),
        }
    except Exception as e:
        return {"error": f"이미지 가져오기 실패: {e}"}


# ── MCP JSON-RPC 배관 ─────────────────────────────────────────────
def send_response(response: dict):
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


TOOLS = [
    {
        "name": "get_workflow",
        "description": "현재 캔버스 전체를 원본 그대로 반환. 개요만 필요하면 summarize_workflow를 쓸 것.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "summarize_workflow",
        "description": "현재 캔버스 요약: 노드 id·타입·제목·위치와 연결 목록. get_workflow보다 가볍다.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_node_types",
        "description": "설치된 노드 타입 검색. 필터 없으면 카테고리 요약. fields로 입출력 타입 추가.",
        "inputSchema": {"type": "object", "properties": {
            "search": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                       "description": "검색어(문자열 또는 배열)"},
            "category": {"type": "string", "description": "카테고리로 필터"},
            "fields": {"type": "array",
                       "items": {"type": "string", "enum": ["inputs", "outputs", "description"]},
                       "description": "추가로 포함할 정보"},
        }, "required": []},
    },
    {
        "name": "get_node_info",
        "description": "캔버스의 특정 노드 상세: 타입·입출력·연결·위젯값.",
        "inputSchema": {"type": "object", "properties": {
            "node_id": {"type": "string", "description": "노드 ID"}}, "required": ["node_id"]},
    },
    {
        "name": "run",
        "description": "워크플로우를 큐에 올려 실행하거나(queue) 현재 생성을 중단(interrupt).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["queue", "interrupt"], "description": "기본 queue"}},
            "required": []},
    },
    {
        "name": "edit_graph",
        "description": ("캔버스를 편집한다(간판 기능). operations를 순서대로 실행. "
                        "action별: create {node_type, pos_x, pos_y, title, ref, place_in_view}, "
                        "delete {node_id 또는 node_ids}, "
                        "move {node_id, x, y} 또는 {node_id, relative_to, direction(right/left/above/below), gap}, "
                        "resize {node_id, width, height}, "
                        "set {node_id, property, value} 또는 {node_id, properties:{k:v}}, "
                        "connect/disconnect {from_node, from_slot, to_node, to_slot}. "
                        "create의 'ref'를 뒤 연산에서 from_node/to_node/node_id로 참조하면 "
                        "한 번에 여러 노드를 만들고 연결할 수 있다. "
                        "place_in_view:true면 노드를 사용자가 지금 보는 화면 중앙에 놓는다."),
        "inputSchema": {"type": "object", "properties": {
            "operations": {"oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}],
                           "description": "연산 하나 또는 배열. 각 연산은 action + 파라미터."}},
            "required": ["operations"]},
    },
    {
        "name": "view_image",
        "description": "Preview/Save Image 노드의 최신 출력 이미지를 가져와 대화창에 표시. 먼저 run으로 실행해야 함.",
        "inputSchema": {"type": "object", "properties": {
            "node_id": {"type": "string", "description": "이미지 노드 ID(생략 시 첫 이미지 노드)"},
            "image_index": {"type": "integer", "description": "여러 장일 때 몇 번째(0부터). 기본 0"}},
            "required": []},
    },
    {
        "name": "center_on_node",
        "description": "사용자 화면을 특정 노드로 스크롤. 노드를 만든 뒤 어디 놓였는지 보여줄 때.",
        "inputSchema": {"type": "object", "properties": {
            "node_id": {"type": "string", "description": "중심에 둘 노드 ID"}}, "required": ["node_id"]},
    },
]


def handle_request(request: dict):
    method = request.get("method", "")
    params = request.get("params", {})
    rid = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "node-smith", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }}

    if method == "notifications/initialized":
        return None  # 알림엔 응답 없음

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "get_workflow":
                result = get_workflow()
            elif name == "summarize_workflow":
                result = summarize_workflow()
            elif name == "get_node_types":
                result = get_node_types(args.get("search"), args.get("category"), args.get("fields"))
            elif name == "get_node_info":
                result = get_node_info(args.get("node_id", ""))
            elif name == "run":
                result = run(args.get("action", "queue"), args.get("node_ids"))
            elif name == "edit_graph":
                result = edit_graph(args.get("operations", []))
            elif name == "view_image":
                result = view_image(args.get("node_id"), args.get("image_index", 0))
            elif name == "center_on_node":
                result = center_on_node(args.get("node_id", ""))
            else:
                return {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        except Exception as e:
            result = {"error": f"도구 실행 실패: {type(e).__name__}: {e}"}

        # 이미지 결과는 image 콘텐츠로 반환해 대화창에 그려지게 한다
        if name == "view_image" and isinstance(result, dict) and "base64_data" in result:
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [
                {"type": "text", "text": f"node {result.get('node_id')} ({result.get('node_title')}): {result.get('filename')}"},
                {"type": "image", "data": result["base64_data"], "mimeType": result.get("media_type", "image/png")},
            ]}}

        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}}

    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            request = json.loads(line)
            rid = request.get("id")
            response = handle_request(request)
            if response:
                send_response(response)
        except json.JSONDecodeError as e:
            send_response({"jsonrpc": "2.0", "id": rid, "error": {"code": -32700, "message": f"Parse error: {e}"}})
        except Exception as e:
            send_response({"jsonrpc": "2.0", "id": rid,
                           "error": {"code": -32000, "message": f"Internal error: {type(e).__name__}: {e}"}})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    main()
