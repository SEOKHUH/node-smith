// node-smith — ② 집배원 + 화가 (browser side)
//
// 집배원: 200ms마다 우편함(/node-smith/graph-command)을 확인해 명령을 꺼내 온다.
// 화가:   꺼낸 명령을 표준 LiteGraph API로 실제 캔버스에 그린다.
// 그리고 2초마다 현재 캔버스 상태를 우편함(/node-smith/workflow)에 올려 둔다.
//
// comfy-pilot js/claude-code.js의 executeGraphCommand / pollGraphCommands / syncWorkflow를
// 우리가 쓰는 액션만 남겨 재현했다 (터미널·플로팅창 UI는 전부 제거).

import { app } from "../../scripts/app.js";

// ── 집배원: 우편함에서 명령 하나를 꺼내 실행하고 결과를 반납 ──
// 여러 브라우저(창)가 같은 서버에 붙어 있으면 명령이 먼저 집는 창으로 흩어진다.
// 그래서 화면에 보이지 않는(최소화·백그라운드) 창은 아예 폴링하지 않는다
// → 사용자가 지금 보고 있는 창 하나만 그림을 그린다.
async function pollGraphCommands() {
    if (document.hidden) return;
    try {
        const res = await fetch("/node-smith/graph-command");
        const data = await res.json();
        if (!data.command) return;

        const result = await executeGraphCommand(data.command);

        await fetch("/node-smith/graph-command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command_id: data.command.id, result }),
        });
    } catch (e) {
        // 조용히 무시 (ComfyUI 재시작 중 등 일시적 실패)
    }
}

// ── 현재 캔버스 상태를 우편함에 올려 둠 (MCP서버의 get_workflow가 읽음) ──
async function syncWorkflow() {
    if (document.hidden) return;  // 안 보이는 창은 캔버스 상태를 덮어쓰지 않는다
    try {
        if (!app.graph) return;
        const workflow = app.graph.serialize();
        await fetch("/node-smith/workflow", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workflow, timestamp: Date.now() }),
        });
    } catch (e) {
        // 무시
    }
}

// ── 화가: 명령을 표준 LiteGraph API로 캔버스에 그린다 ──
async function executeGraphCommand(command) {
    const { action, params } = command;
    try {
        if (!app.graph) return { error: "Graph not available" };

        switch (action) {
            case "create_node": {
                const node = LiteGraph.createNode(params.type);
                if (!node) return { error: `Unknown node type: ${params.type}` };

                node.pos = findFreePosition(node, params);
                if (params.title) node.title = params.title;

                app.graph.add(node);
                app.graph.setDirtyCanvas(true, true);
                return {
                    status: "created",
                    node_id: node.id,
                    type: params.type,
                    title: node.title,
                    pos: node.pos,
                };
            }

            case "delete_node": {
                const node = app.graph.getNodeById(parseInt(params.node_id));
                if (!node) return { error: `Node ${params.node_id} not found` };
                app.graph.remove(node);
                app.graph.setDirtyCanvas(true, true);
                return { status: "deleted", node_id: params.node_id };
            }

            case "set_node_property": {
                const node = app.graph.getNodeById(parseInt(params.node_id));
                if (!node) return { error: `Node ${params.node_id} not found` };

                let found = false;
                if (node.widgets) {
                    for (const w of node.widgets) {
                        if (w.name === params.property_name) {
                            w.value = params.value;
                            if (w.callback) w.callback(params.value, app.canvas, node, [0, 0], null);
                            found = true;
                            break;
                        }
                    }
                }
                if (!found) {
                    return { error: `Widget '${params.property_name}' not found on node ${params.node_id}` };
                }
                app.graph.setDirtyCanvas(true, true);
                return { status: "updated", node_id: params.node_id, property: params.property_name, value: params.value };
            }

            case "connect_nodes": {
                const fromNode = app.graph.getNodeById(parseInt(params.from_node_id));
                const toNode = app.graph.getNodeById(parseInt(params.to_node_id));
                if (!fromNode) return { error: `Source node ${params.from_node_id} not found` };
                if (!toNode) return { error: `Target node ${params.to_node_id} not found` };

                const link = fromNode.connect(params.from_slot, toNode, params.to_slot);
                app.graph.setDirtyCanvas(true, true);
                return {
                    status: link ? "connected" : "failed",
                    from_node: params.from_node_id, from_slot: params.from_slot,
                    to_node: params.to_node_id, to_slot: params.to_slot,
                    link_id: link ? link.id : null,
                };
            }

            case "disconnect_nodes": {
                const toNode = app.graph.getNodeById(parseInt(params.to_node_id));
                if (!toNode) return { error: `Target node ${params.to_node_id} not found` };
                if (toNode.inputs && toNode.inputs[params.to_slot]) {
                    const linkId = toNode.inputs[params.to_slot].link;
                    if (linkId !== null) app.graph.removeLink(linkId);
                }
                app.graph.setDirtyCanvas(true, true);
                return { status: "disconnected", to_node: params.to_node_id, to_slot: params.to_slot };
            }

            case "move_node": {
                const node = app.graph.getNodeById(parseInt(params.node_id));
                if (!node) return { error: `Node ${params.node_id} not found` };

                if (params.relative_to != null && params.direction) {
                    // 다른 노드 기준 상대 배치: "A의 오른쪽/왼쪽/위/아래에 gap만큼 띄워 둠"
                    const ref = app.graph.getNodeById(parseInt(params.relative_to));
                    if (!ref) return { error: `Reference node ${params.relative_to} not found` };
                    const gap = params.gap != null ? params.gap : 30;
                    const rp = ref.pos, rs = ref.size || [200, 100];
                    const ns = node.size || [200, 100];
                    switch (params.direction) {
                        case "right": node.pos = [rp[0] + rs[0] + gap, rp[1]]; break;
                        case "left":  node.pos = [rp[0] - ns[0] - gap, rp[1]]; break;
                        case "below": node.pos = [rp[0], rp[1] + rs[1] + gap]; break;
                        case "above": node.pos = [rp[0], rp[1] - ns[1] - gap]; break;
                        default: return { error: `Unknown direction: ${params.direction}` };
                    }
                } else if (params.x != null && params.y != null) {
                    node.pos = [params.x, params.y];
                }

                if (params.width || params.height) {  // resize
                    const cur = node.size || [200, 100];
                    node.size = [params.width || cur[0], params.height || cur[1]];
                }
                app.graph.setDirtyCanvas(true, true);
                return { status: "moved", node_id: params.node_id, pos: node.pos, size: node.size };
            }

            case "center_on_node": {
                const node = app.graph.getNodeById(parseInt(params.node_id));
                if (!node) return { error: `Node ${params.node_id} not found` };
                if (app.canvas && app.canvas.centerOnNode) {
                    app.canvas.centerOnNode(node);
                    return { status: "centered", node_id: params.node_id };
                }
                return { error: "Canvas centerOnNode not available" };
            }

            case "queue_prompt": {
                // 브라우저에서 큐에 올려야 client_id가 맞아 미리보기 이미지가 UI에 뜬다.
                await app.queuePrompt(0, 1);
                return { status: "queued" };
            }

            default:
                return { error: `Unknown action: ${action}` };
        }
    } catch (e) {
        return { error: e.message || String(e) };
    }
}

// 새 노드가 기존 노드와 안 겹치게 빈 자리를 찾는다 (없으면 오른쪽으로 밀어 둠).
// place_in_view면 시작점을 "사용자가 지금 보는 화면 중앙"으로 잡는다.
function findFreePosition(node, params) {
    const w = node.size ? node.size[0] : 200;
    const h = node.size ? node.size[1] : 100;
    const gap = 30;
    let startX, startY;

    if (params.place_in_view && app.canvas) {
        // 화면(스크린) 좌표 → 그래프 좌표: graphPos = (screenPos - offset) / scale
        const c = app.canvas;
        const offset = c.ds.offset, scale = c.ds.scale;
        const sidebar = 130;  // 왼쪽 사이드바만큼 중앙을 왼쪽으로 보정
        const screenCX = (c.canvas.width - sidebar) / 2;
        const screenCY = c.canvas.height / 2;
        startX = (screenCX - offset[0]) / scale - w / 2 + (params.viewport_offset || 0);
        startY = (screenCY - offset[1]) / scale - h / 2;
    } else {
        startX = params.pos_x != null ? params.pos_x : 100;
        startY = params.pos_y != null ? params.pos_y : 100;
    }

    const collides = (x, y) => {
        for (const other of app.graph._nodes) {
            if (other === node) continue;
            const ox = other.pos[0], oy = other.pos[1];
            const ow = other.size ? other.size[0] : 200;
            const oh = other.size ? other.size[1] : 100;
            if (x < ox + ow && x + w > ox && y < oy + oh && y + h > oy) return true;
        }
        return false;
    };

    if (!collides(startX, startY)) return [startX, startY];
    const dirs = [[1, 0], [0, 1], [-1, 0], [0, -1]];
    for (let d = 1; d <= 10; d++) {
        for (const [dx, dy] of dirs) {
            const x = startX + dx * (w + gap) * d;
            const y = startY + dy * (h + gap) * d;
            if (!collides(x, y)) return [x, y];
        }
    }
    return [startX + w + gap, startY];
}

app.registerExtension({
    name: "node-smith",
    async setup() {
        pollGraphCommands();
        setInterval(pollGraphCommands, 200);
        setInterval(syncWorkflow, 2000);
        console.log("[node-smith] 집배원 가동: 200ms 폴링 + 2초 캔버스 동기화");
    },
});
