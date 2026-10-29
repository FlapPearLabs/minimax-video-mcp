# 审查报告 · WorkBuddy（claude-opus-4-6-thinking）

> 对抗式代码审查，独立 clone、独立写探针，未使用真实 API key、未发起计费生成。
> 审查简报见 `docs/REVIEW-BRIEF.md`。

---

## Q1 官方视频能力边界

官方"视频能力"横跨四层，以下为完整清单（已确认，来源均为本机实际文件与命令输出）。

### 连接器侧（`mcode-tools connector tools` 输出，共 19 工具中的视频直接相关 3 个）

| 工具名 | 功能 | 换服务商后应保留？ |
|--------|------|----|
| `connector__matrix__submit_video_generation` | 异步提交视频生成，返回 task_id | **是**（核心生成） |
| `connector__matrix__query_video_generation` | 查询任务状态/结果，含 node_id/file_name | **是**（核心查询） |
| `connector__matrix__videos_understand` | 视频问答（Q&A），给 URL + prompt，得到理解结果 | **是**（视频理解） |

连接器还有 10 个**媒体相关**工具（图片/语音/音乐/音频），其中 `synthesize_speech` / `batch_text_to_audio` / `batch_text_to_music` / `generate_image` 在完整视频制作流程中常被调用：

| 工具 | 角色 | 换服务商后应保留？ |
|------|------|----|
| `connector__matrix__generate_image` | 生成首帧/参考图 | **是** |
| `connector__matrix__synthesize_speech` | 配音（Hailuo-2.3 是静音的，需要 TTS） | **是** |
| `connector__matrix__batch_text_to_audio` | 批量 TTS | 是 |
| `connector__matrix__batch_text_to_music` | 生成 BGM/音乐 | 是 |
| `connector__matrix__describe_images` | 图片理解 | 是 |
| `connector__matrix__get_voice_list` | TTS 声库列表 | 是 |
| `connector__matrix__listen_audio` | 音频转文字 | 是 |
| `connector__matrix__audios_understand` | 音频问答 | 是 |
| `connector__matrix__search_images` / `reverse_image_search` | 图片搜索 | 是 |

**证据**: `mcode-tools connector tools` 命令完整输出 + `mcode-tools connector tool <name>` 获取的每个工具 input_schema。

### 插件侧（minimax-video 插件）

1. **`openchatcut` MCP**（`servers.mcp.json:4-10`）: streamable-http MCP，描述为"读取视频工程、创建编辑草稿、剪辑时间线并提交审阅"。即**视频修改/编辑**能力。通过 miniapp (`server.mjs`) 暴露。工具包括：
   - `read_timeline` / `add_motion_graphic` / `update_item_props` / `move_item` / `set_item_timing` / `duplicate_item` / `remove_item` / `split_item` / `add_audio` / `list_audio` / `list_templates` / `search_templates` / `submit_motion_graphic` / `export_jianying_draft` 等（`openchatcut-tool-schemas.json`）
   - **这是完整的非线性编辑(NLE)接口**：时间线读写、素材池管理、模板系统、剪映导出。
   - 换服务商后**应保留**（它操作本地工程，不直接调API生成视频）。

2. **Skills（minimax-video 插件内）**:
   - `code-video`: 用代码动画做可编辑的视频片头/图表/讲解（使用 openchatcut MCP 的工具）。**无 Hub 依赖，可独立运行**。
   - `lucid`: 用 Lucid 引擎代码渲染 MP4，再导入编辑器。**无 Hub 依赖，可独立运行**。

### Hub agent 侧（`hub_*` 工具）

H3 skills 的 frontmatter 列出的 `allowed-tools`:
- `hub_generate_video` — 视频生成（Hub 封装，内部调 connector 层）
- `hub_video_edit` — **视频修改/编辑**（剪辑/装配）
- `hub_generate_image` / `hub_generate_audio` / `hub_generate_music` / `hub_synthesize_speech` — 多媒体生成
- `hub_analyse_media` — 媒体分析
- `hub_canvas_get_node` / `hub_canvas_group_recent_outputs` — canvas 工作区
- `hub_image_search` / `hub_audio_meta` — 搜索/元数据

**关键事实（已确认）**: `hub_*` 工具**不在** `mcode-tools connector tools` 输出里，也**不在**本机任何 MCP 配置或 miniapp 代码中。它们由 **MiniMax Hub agent 运行时**提供 — 一个服务端组件，非本地可控。8/9 个 H3 skills 明确写着 `compatibility: Requires the MiniMax Hub agent; not portable to generic agent harnesses`。唯一例外是 `h3-prompt-writing`（纯文本处理，标注为 Portable）。

### Skills 侧（minimax-h3-skills 插件，9 个 skill）

| Skill | Hub 依赖 | 说明 |
|-------|----------|------|
| `h3-prompt-writing` | 无（Portable） | H3 提示词撰写指南，纯文件读取 |
| `brand-promo-video-generator` | **Hub required** | 品牌宣传片，完整制作流 |
| `3d-animation-short-generator` | **Hub required** | 3D动画短片 |
| `co-op-game-intro-generator` | **Hub required** | 游戏宣传片 |
| `handdrawn-live-video-generator` | **Hub required** | 手绘风视频 |
| `minimalist-product-ad-generator` | **Hub required** | 极简产品广告 |
| `music-video-subtitle-generator` | **Hub required** | 音乐视频+字幕 |
| `paper-collage-explainer-generator` | **Hub required** | 纸质拼贴讲解 |
| `papercraft-stop-motion-explainer` | **Hub required** | 定格动画讲解 |

**证据**: 每个 SKILL.md 的 `compatibility` 行。路径: `C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-11421417a64d00605ec71d4d50200f6ea63e5b70f0e2e780fe9a5161d352e20a\skills\*\SKILL.md`

---

## Q2 差距清单

### 2.1 工具名命名空间不匹配

| 官方工具名 | 项目工具名 | 匹配？ |
|-----------|-----------|-------|
| `connector__matrix__submit_video_generation` | `submit_video_generation` | **不匹配** |
| `connector__matrix__query_video_generation` | `query_video_generation` | **不匹配** |
| `connector__matrix__videos_understand` | （无） | **缺失** |

**影响判定（已确认）**：
- 官方 H3 skills（8个需 Hub 的）使用 `hub_generate_video` / `hub_video_edit`，**不是** `connector__matrix__*`。Hub agent 内部再调 connector 层。所以即使把工具名改成 `connector__matrix__*`，H3 skills 仍然跑不起来（它们需要 Hub agent 运行时）。
- `code-video` 和 `lucid` skills 不调视频生成连接器，它们用的是 openchatcut MCP 的本地工具。所以命名空间不影响它们。
- **结论**: 改工具名到 `connector__matrix__*` 命名空间是方向正确的（直接替换连接器场景），但**不能让官方 H3 skills 原样跑起来**。

### 2.2 缺失能力

| 能力 | 官方有 | 项目有 | 差距 |
|------|--------|--------|------|
| **视频理解** (`videos_understand`) | 有 | **无** | 完全缺失 |
| **图片生成** (`generate_image`) | 有 | **无** | 完全缺失 |
| **TTS** (`synthesize_speech` / `batch_text_to_audio`) | 有 | **无** | 完全缺失 |
| **音乐生成** (`batch_text_to_music`) | 有 | **无** | 完全缺失 |
| **音频理解** (`audios_understand` / `listen_audio`) | 有 | **无** | 完全缺失 |
| **图片描述** (`describe_images`) | 有 | **无** | 完全缺失 |
| **图片搜索** (`search_images` / `reverse_image_search`) | 有 | **无** | 完全缺失 |
| **TTS声库** (`get_voice_list`) | 有 | **无** | 完全缺失 |
| **视频编辑** (openchatcut MCP: timeline, templates, export) | 有 | **无** | 完全缺失 |
| `MiniMax-Hailuo-2.3` 模型 | 有（官方 schema 列出三个模型） | **无**（provider.json 只配 H3/H3-Max） | 缺失 |
| `node_id` / `file_name` 返回 + `get_asset_url` 取直链 | 有（官方 query 返回） | 无（返回 `video_url` 直链） | **返回结构不一致** |
| `reference_type` 参数 | 有（`first_frame` / `last_frame` / `subject`） | 无（用 `input_image` + role 映射隐式实现） | 参数接口不一致 |
| `input_image.mime_type` | 有 | 无 | 缺失 |
| `reference_videos[].duration_seconds` | 有（required） | 无 | 缺失 |

### 2.3 请求体差异

**已确认**: 项目采用 MiniMax V2 content 数组格式（`server.py:308-330`），与官方 API 请求体结构**基本一致**。但:

1. 官方连接器的 `input_schema` 是**平铺参数**（`prompt`, `model`, `input_image`, `last_frame_image`, `reference_images`, `reference_videos`, `reference_audios`, `ratio`, `resolution`, `duration`, `reference_type`），内部转换为 V2 content 数组。项目也是平铺参数 → content 数组，逻辑一致。
2. 官方多一个 `reference_type` 枚举（`first_frame` / `last_frame` / `subject`）。项目用 `input_image` 参数 + `roles` 映射隐式决定 role，没有 `reference_type`。
3. 官方 `model` 是 required enum 包含三值 (`MiniMax-H3`, `MiniMax-H3-Max`, `MiniMax-Hailuo-2.3`)。项目 `model` 是 optional 默认 `MiniMax-H3`。
4. 官方 `query_video_generation` 的 `model` 是 **required**。项目的 `model` 是 optional。

### 2.4 返回结构差异

**已确认**: 官方 `query_video_generation` 返回 `node_id` + `file_name`，需要再调 `get_asset_url` 获取短时直链。项目直接返回 `video_url`（中转站的查询接口直接返回直链 `task.content.url`）。这不是"不一致"而是**中转站的接口行为差异**（AGENTS.md 的九处差异之一）。

### 2.5 "视频修改"这条线

**官方做法**:
- **openchatcut MCP**（minimax-video 插件）: 完整的非线性编辑器，支持时间线操作、模板、素材池、剪映导出。由 `server.mjs` 本地运行。
- **`hub_video_edit`** 工具（Hub agent）: H3 skills 用它做视频装配/剪辑。
- `code-video` / `lucid` skills: 代码生成视频 → 导入 openchatcut 编辑器。

**项目做法**: **完全没有视频编辑能力**。没有 openchatcut MCP、没有时间线操作、没有模板系统、没有剪映导出。项目只做"提交-轮询-下载"。

---

## Q3 路线评估

### 路线 A：直接替换官方插件/Hub 的上游 base_url

**改动点**: 找到 Hub agent 或 connector 层读取的 API endpoint 配置，改成 `https://api.lk888.ai`。

**可行性分析（已确认）**:
- `hub_*` 工具由 MiniMax Hub agent 运行时提供，这是一个**服务端组件**。本机没有 `hub_*` 的实现代码，grep 整个 `.minimax` 目录也找不到。**无法在本地替换上游**。
- `connector__matrix__*` 由 `mcode-tools` 的 connector 框架提供，其配置存在 `C:\Users\ssy\.minimax\integrations\mcode-tools`。理论上可以修改 connector 配置指向中转站，但：
  - 这会修改官方安装物（违反"只读"约束）
  - connector 层的返回格式（`node_id` + `get_asset_url`）与中转站不同（中转站直返 `video_url`）
  - connector 层支持 `upload_temp_url`（中转站未必支持）
  - 8 个 H3 skills 依赖 Hub agent 运行时，换 connector 上游**不影响它们**

**达成度**: ~30%。能替换 connector 层的视频生成/查询，但 Hub agent 无法替换，H3 skills 跑不了，编辑能力不受影响（openchatcut 是本地的）。

**风险**: 高。改官方安装物，官方升级会覆盖。connector 返回结构不兼容需要适配层。

**可维护性**: 差。每次官方升级都要重新改。

### 路线 B：自建 MCP，工具名逐字对齐 `connector__matrix__*`

**改动点**:
1. `server.py`: 工具名加 `connector__matrix__` 前缀
2. 补齐 `videos_understand`、`generate_image`、`synthesize_speech`、`batch_text_to_audio`、`batch_text_to_music`、`describe_images`、`search_images`、`reverse_image_search`、`get_voice_list`、`listen_audio`、`audios_understand`
3. 返回结构对齐（模拟 `node_id` + 兼容 `get_asset_url` 调用模式）
4. 补 `MiniMax-Hailuo-2.3` 模型支持
5. 补 `reference_type` 参数
6. 注册为 MCP 替代 connector

**工作量**: 大。需要实现 11+ 个新工具。中转站未必支持所有 API（图片/语音/音乐）。需要返回格式适配层。

**达成度**: ~55%。能覆盖连接器层全部工具面。但 H3 skills（8个 Hub-dependent）仍然跑不了。openchatcut 编辑能力也不在此方案范围。

**风险**: 中。中转站可能不支持所有多媒体 API。返回结构适配容易出 bug。

**可维护性**: 中。官方加新工具或改 schema 需要跟进。

### 路线 C：保留现有实现，改官方 skills 里的工具名引用

**改动点**: 批量替换 H3 skills 的 SKILL.md 中 `hub_*` → 自建 MCP 工具名。

**可行性分析（已确认）**: **不可行**。
- 8 个 H3 skills 声明 `compatibility: Requires the MiniMax Hub agent; not portable to generic agent harnesses`。它们不仅依赖工具名，还依赖 **Hub agent 运行时的 canvas workspace、choice cards 等基础设施**。改工具名解决不了 canvas/选择卡片等运行时依赖。
- `code-video` 和 `lucid` 不依赖 `hub_*`，它们用 openchatcut MCP，不需要改。

**达成度**: ~5%。基本不可行。

**风险**: 极高。改了工具名 skills 也跑不起来，白费功夫。

**可维护性**: 差。

### 路线 D：兼容/别名 + 路由层

**改动点**:
1. 自建 MCP 注册时同时暴露 `connector__matrix__submit_video_generation` 和 `submit_video_generation` 两个别名
2. 添加路由层，当 Agent 调 `connector__matrix__*` 时转发到自建 MCP

**达成度**: 与路线 B 等效（~55%），只是多了命名空间兼容。Hub 依赖问题同样无法解决。

**风险/可维护性**: 同路线 B。

### 补充路线 E：在路线 B 基础上集成 openchatcut

**改动点**: 路线 B + 把官方 openchatcut miniapp（`server.mjs`）作为子进程或 sidecar 启动，配置为同一 MCP server 的一部分。

**达成度**: ~70%。能覆盖连接器层 + 编辑能力。但 Hub agent 的 canvas/choice cards 仍然缺失，8 个 H3 skills 仍然跑不了。

**风险**: 高。openchatcut 是 AGPL-3.0 许可，直接集成有合规风险。miniapp 有 npm 依赖和 native 依赖（`sqlite-vec`）。

---

## Q4 判定 + 最小改动清单

### 判定：**当前项目无法达到"与官方完全等价"的要求。**

**核心阻断因素（已确认，非推断）**:

1. **Hub agent 运行时是服务端封闭组件**。8/9 个 H3 skills 依赖它（canvas workspace、choice cards、`hub_*` 工具），无法在本地替换或模拟。这不是"补代码"能解决的问题。
2. **视频编辑能力完全缺失**。openchatcut 是一个独立的复杂 Web 应用 + Node 后端（`server.mjs`, Remotion bundle, ffmpeg 依赖），不是"加个 MCP 工具"就能补的。
3. **多媒体能力矩阵缺失**。中转站 `api.lk888.ai` 是否支持图片生成/TTS/音乐生成/视频理解等 API **未验证**（需要真实 key 才能确认，本次审查不允许使用）。

### 最小改动清单（按优先级排序，达到"尽可能接近"而非"完全等价"）

| 优先级 | 改动 | 目的 | 验收方式 | 预期达成 |
|--------|------|------|----------|----------|
| **P0** | 工具名加 `connector__matrix__` 前缀 | 命名空间对齐，Agent 侧可复用官方调用习惯 | `mcp list` 看到前缀工具名 | 解决命名不匹配 |
| **P0** | 补 `videos_understand` 工具 | 补最关键的视频理解缺口 | 工具调用返回视频描述 | 前提：中转站需支持此 API |
| **P1** | `query` 返回增加 `node_id` + `file_name` 模拟字段 | 返回结构对齐 | Agent 可用 `get_asset_url(node_id)` 模式取 URL | 向前兼容 |
| **P1** | 补 `MiniMax-Hailuo-2.3` 模型支持 | 模型覆盖对齐 | submit 可传此模型 | 前提：中转站支持 |
| **P1** | 补 `reference_type` 参数 | 参数接口对齐 | 传 `subject` 模式可工作 | 前提：中转站支持 |
| **P2** | 补 `generate_image` / `synthesize_speech` / `batch_text_to_music` 等多媒体工具 | 完整视频制作流程需要 | 各工具可正常调用 | 前提：中转站支持这些 API |
| **P3** | 集成 openchatcut 编辑能力 | 补视频编辑缺口 | 时间线操作可用 | 工作量大，AGPL 合规 |
| **不可达** | 替换 Hub agent 运行时 | 让 H3 skills 跑起来 | — | **不可行**：封闭服务端组件 |

---

## Q5 下一步

**先用真实 key 在中转站上探测完整的 API 覆盖面。**

具体动作：拿 `api.txt` 里的 key，对 `https://api.lk888.ai` 逐个调用 `GET /v1/models`（确认模型列表）、`POST /v2/video_generation`（不实际提交，看 schema 报错）、以及图片/语音/音乐的对应端点（`POST /v1/images/generations`、`POST /v1/audio/speech`、`POST /v1/audio/transcriptions` 等常见 OpenAI 兼容路由），确认中转站到底支持哪些能力。这决定了 P0-P2 改动中哪些实际可行，哪些因上游不支持而需要放弃。不需要花钱，只需要看 401→200 路由是否存在。在此之前做任何代码改动都可能白费。

---

## 未验证项

| 项目 | 原因 | 影响 |
|------|------|------|
| 中转站是否支持 `MiniMax-Hailuo-2.3` | 需要真实 key + `GET /v1/models` | 决定 P1 模型覆盖是否可行 |
| 中转站是否支持图片/TTS/音乐 API | 需要真实 key 探测端点 | 决定 P2 多媒体工具是否可行 |
| 中转站是否支持视频理解 API | 需要真实 key | 决定 P0 `videos_understand` 是否可行 |
| `get_asset_url` 在 connector 层的具体实现 | 未在 `mcode-tools connector tools` 输出中看到此工具名，推断它可能是 connector 框架内置方法而非独立工具 | 影响返回结构对齐的设计 |
| openchatcut MCP 的 `http://127.0.0.1:9/mcp/openchatcut` 端口 9 | 显然不是真实端口，推断由 miniapp 框架动态分配 | 影响 P3 集成方案设计 |
| Hub agent `hub_*` 工具的内部实现是否调用 `connector__matrix__*` | 推断如此（Hub 是 connector 的上层封装），但未确认 | 影响路线 A 的理论可行性判断 |
| 项目的 `_build_content_array` 是否能完全覆盖官方所有 content 组合 | 代码逻辑审查通过，但未用真实 key 实测 | 影响请求兼容性 |
