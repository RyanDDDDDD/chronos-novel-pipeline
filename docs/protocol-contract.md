# 交互载荷契约（单一规格源）

> **范围**：主笔写作循环（`author_loop` · **dialogue mode**）的 WebSocket 出站事件与 REST 命令。  
> 旧 classic 路径的 `author_loop_prompt` / `author_loop_reply`、DAG 时代的 `refine_proposal` / `refine_segment_review` 与 `api/protocol.py` codec **已退役**（载荷形状见 `docs/archive/` 若需对照）。

前端实现：`src/frontend/src/hooks/useOrchestrator.ts`（消费 `author_loop_*` 广播）。  
后端实现：`api/services/message_hub.py`（`start_author_loop` → `run_dialogue_chapter`）。

---

## 1. 通信模型

- **WebSocket `/ws`**：服务端→客户端**单向广播**；客户端不通过 WS 回传写作指令。
- **REST**：启动 / 停止 / 续跑 / 保存等命令走 HTTP。
- **Replay Buffer**：新连接重放历史事件；`author_loop_token` 与 `setup_chat_token` 等高频 ephemeral 事件**不重放**（见 `gateway.py`）。

---

## 2. 出站事件（live · dialogue mode）

### 2.1 章级生命周期

```json
{"type": "author_loop_start", "chapter": 1, "resume": false}
```

```json
{"type": "author_loop_done", "chapter": 1, "mode": "dialogue"}
```

```json
{"type": "author_loop_error", "error": "…"}
```

```json
{"type": "author_loop_stopped", "chapter": 1, "reason": "…"}
```

| 字段 | 说明 |
|------|------|
| `resume` | `start` 时 `true` 表示从 SQLite 检查点续跑 |
| `mode` | `done` 时固定 `"dialogue"` |

### 2.2 beat 级进度

```json
{"type": "author_loop_chapter_progress", "done": 3, "total": 12}
```

驱动前端顶栏进度条；`done` 为已完成 beat 数。

### 2.3 流式落字

```json
{"type": "author_loop_token", "agent": "synthesis", "delta": "…"}
```

| 字段 | 说明 |
|------|------|
| `agent` | 流式来源标签（如 `synthesis`） |
| `delta` | 增量文本片段 |

前端用 `live` 气泡累积 `delta`；`author_loop_segment` 定稿后清空 `live`。

### 2.4 定稿 beat 正文

```json
{
  "type": "author_loop_segment",
  "index": 0,
  "beat": 0,
  "beats": 1,
  "intent": "本 beat 意图摘要",
  "text": "定稿正文…",
  "draft": false,
  "agent": "synthesis",
  "role": null,
  "total": 12
}
```

| 字段 | 说明 |
|------|------|
| `index` | beat 序号（0 基） |
| `draft` | `true`=流式中间态；journal 通常只持久化 `draft=false` |
| `agent` / `role` | dialogue mode 按 agent 分气泡；classic 契约可省略 |

### 2.5 角色状态推演

```json
{
  "type": "author_loop_state",
  "index": 0,
  "entry": false,
  "characters": [{"name": "…", "state": "…", "…": "…"}],
  "mode": "dialogue"
}
```

| 字段 | 说明 |
|------|------|
| `entry` | `true` 表示章初入场态（`index=-1`）；否则为本 beat 推演结果 |
| `characters` | 各角色微状态卡片行 |

### 2.6 场景生图（侧车，不进 journal）

```json
{"type": "author_scene_image_started", "chapter": 6, "index": 2}
```

```json
{"type": "author_scene_image_done", "chapter": 6, "index": 2, "filename": "6_2-1730000000.png"}
```

| `type` | 方向 | 说明 |
|--------|------|------|
| `author_scene_image_started` | 出 | 某 stage 场景生图开始（侧车，不进 journal） |
| `author_scene_image_done` | 出 | `{chapter, index, filename?}` 或 `{chapter, index, error}` |

### 2.7 其它出站（journal / 兼容）

| `type` | 说明 |
|--------|------|
| `author_loop_summary` | 滚动摘要行（journal 重放用） |

---

## 3. REST 触发

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| `POST` | `/api/author-loop/start` | `{"chapter": N, "fresh?": bool, "prose_style?": str}` | 启动主笔 |
| `POST` | `/api/author-loop/resume` | `{"chapter": N, …}` | 从检查点续跑 |
| `POST` | `/api/author-loop/stop` | — | 取消运行中任务 |
| `POST` | `/api/author-loop/save` | `{"chapter": N}` | 检查点 → `第N章_主笔.md` |
| `GET` | `/api/author-loop/status` | — | 可续跑章节列表 |
| `GET` | `/api/author-loop/journal?chapter=N` | — | 章级事件日志重放 |
| `GET/PUT` | `/api/author-loop/dialogue-config` | — | dialogue 模式配置 |
| `POST` | `/api/author-loop/scene-image` | `{"chapter": N, "index": M}` | 触发某 stage 场景生图 |
| `GET` | `/api/author-loop/scene-images?chapter=N` | — | `{stage_index: url}` |
| `GET` | `/api/author-loop/scene-image/{chapter}/{index}/file` | — | PNG |

> classic 路径的 `GET/PUT /api/author-loop/skills` 若仍暴露，仅供遗留 skill 编排 UI；dialogue 热路径不读取。

---

## 4. 已退役：写作期双向交互

classic 主笔在写作期通过 WebSocket 弹出选项卡，载荷如下（**代码已移除，仅 journal 历史可见**）：

<details>
<summary><code>author_loop_prompt</code> / <code>author_loop_reply</code>（点击展开）</summary>

出站 `author_loop_prompt`：

```json
{
  "type": "author_loop_prompt",
  "prompt_id": 1,
  "kind": "choice",
  "index": 0,
  "beat": 0,
  "skill": "pose",
  "scope": "",
  "multi": false,
  "options": [{"index": 1, "label": "方案 A"}]
}
```

入站 `author_loop_reply`：

```json
{"type": "author_loop_reply", "prompt_id": 1, "payload": {"choice": 1}}
```

`kind=review` 时 payload 为 `{"action": "accept"}` 或 `{"action": "rewrite", "feedback": "…"}`。

</details>

**迁移说明**：skill 选择与骨架方向交互前移到 **Setup Chat**（`setup_chat_*` 事件族）；主笔循环变为非交互流式写作。

---

## 5. 容错

- 无挂起 prompt Future（dialogue mode 常态）→ 无 stale reply 问题。
- 主动 `stop` 广播 `author_loop_stopped`；journal 重放时在末尾补发 `stopped` 以防前端误判为运行中。
- 无头模式（测试）：hub 注入 fake `author_turns` / `derive_turn`，不经 WebSocket。

---

*2026-07-06 | 对齐 dialogue mode 主路径*
