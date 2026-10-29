# AGENTS.md

> 这份文件是给 **AI Agent** 看的。如果你是在 MiniMax Code / Claude Code / Cursor 里操作，
> 读完这一节就能独立完成安装，不需要再问用户任何配置细节。

## 这是什么

一个 MCP server，把 MiniMax Code 的视频生成能力接到第三方中转站（七七八AI）上。

**核心约束：用户只会把 API Key 写进 `api.txt`。不要让用户改任何其他文件、不要让用户配置任何东西。**

## 用户已经做了 / 你要做的

| 谁 | 做什么 |
| --- | --- |
| 用户 | 在中转站注册、拿 API key、把它写进仓库根目录的 `api.txt`（一行） |
| 你 | 克隆仓库 → 确认 key → 注册 MCP server → 验证 → 报告 |

## 仓库结构

```
minimax-video-mcp/
├── README.md            给人看的
├── AGENTS.md            你正在看的
├── 接入提示词.md         给用户复制粘贴用的提示词（内容与本文件一致）
├── api.txt.example      key 模板 → 用户复制成 api.txt
├── api.txt              ← 用户的 key（已被 .gitignore 忽略）
├── provider.json        站点端点 / content 角色表 / 状态映射 / 平台规则
├── provider.example.json 通用模板（换厂商时用）
├── server.py             MCP server（对外工具）
├── keyfile.py            key 解析（容错）
├── install.py            一键安装 / 自检
├── mock_provider.py      本地假厂商
├── requirements.txt
└── tests/                测试套件
```

## 站点接口事实（已核实，直接用，不要再调研）

- **Base URL**：`https://api.lk888.ai`（备用 `https://ai778.cc/houduan`）
- **鉴权**：`Authorization: Bearer sk-xxx`（兼容 `x-api-key` / `x-goog-api-key` / `?key=`）
- **创建任务**：`POST /v2/video_generation`
- **查询任务**：`GET /v2/query/video_generation/{task_id}`
- **任务列表**：`GET /v2/query/video_generation?page_num=1&page_size=20`（page_size ≤ 50，仅近 7 天）
- **删除任务**：`DELETE /v2/video_generation/{task_id}`（只能删已结束的）
- **768P 升 2K**：`POST /v2/video_regeneration`，body 用 `source_task_id` 或 `content:[{type:"video_url", role:"base_video", video_url:{url}}]`
- **模型**：`MiniMax-H3`（推荐，全形态：文生/首尾帧/参考生/全能参考，768P~4K，4~15 秒，2K 有声）、`MiniMax-H3-Max`
- 请求体与 **MiniMax 官方 V2 同形**（`model` / `content[]` / `resolution` / `duration` / `ratio` /
  `callback_url` / `extra` / `aigc_watermark`）—— 同一个模型、同样的参数。
  但接口行为有九处差异，见下节，**别对用户说"完全一致"**。

### content[] 角色表

| type | role | 数量 | 说明 |
| --- | --- | --- | --- |
| `text` | — | 1 | 提示词，必填 |
| `image_url` | `first_frame` | 0~1 | 首帧图；只传一张且不写 role 也算首帧 |
| `image_url` | `last_frame` | 0~1 | 尾帧图，**必须与 first_frame 同传** |
| `image_url` | `reference_image` | 0~9 | 参考图，仅 MiniMax-H3 |
| `video_url` | `reference_video` | 0~3 | 参考视频，仅 MiniMax-H3，**只收公网 URL** |
| `audio_url` | `reference_audio` | 0~3 | 参考音频，仅 MiniMax-H3 |

### 平台规则（server.py 已在提交前拦截，但你也要知道）

1. `resolution` 与 `duration` **必填**，缺了直接 400
2. 文生视频**必须**给具体 `ratio`，且**不能是 `adaptive`**
3. 图生视频 `ratio` 恒按 `adaptive` 处理
4. **只传 `last_frame` 返回 400**
5. **帧模式与参考模式互斥**
6. `POST /v2/h3_context_ir` 平台未接入，固定 400 —— 别去试
7. 不支持 `mm_file://`；图片/音频可公网 URL 或 `data:` 内联；视频只收公网 URL
8. `failed` 任务**已自动退款**，不要重复提交同一任务
9. 轮询建议 **5~10 秒一次**；768P 通常 1~4 分钟出片，1080P/2K/4K 更久

## 接入步骤

### 1. 确认仓库和 key

如果用户给的是 GitHub 链接，先克隆：

```bash
git clone <url>
cd minimax-video-mcp
```

key 必须在**仓库根目录的 `api.txt`**。用户没写就问他要（或请他把 key 给你，由你写进 `api.txt`）。

### 2. 跑自检

```bash
python install.py
```

它会打印 key 来源、验证结果、可用视频模型、测试结果，以及注册参数。

**如果它失败**，按输出的提示处理，别自己瞎改 `provider.json`：

| 报错 | 处理 |
| --- | --- |
| 没找到 API key | 确认 `api.txt` 在仓库根目录、key 在第一行 |
| 401 | key 抄错，或用了 MiniMax 官方 key |
| 403 ip_not_allowed | 提醒用户在控制台把本机 IP 加进白名单 |
| 402 | 提醒用户充值 |
| 连不上 | 检查网络/代理；或确认 `provider.json` 的 `base_url` |

### 3. 注册 MCP server

用 `mavis` 工具（不要手敲 CLI）：

```
mcp create
  name        = minimax-video
  transport   = stdio
  command     = python
  args        = ["<仓库绝对路径>/server.py"]
  description = 第三方中转站 MiniMax 视频生成
```

**不要传 `env`** —— `server.py` 会自己读同目录的 `api.txt`。
如果用户希望 key 不落盘，改用 `env={"VIDEO_API_KEY": "<key>"}`（优先级更高）。

如果 `mcp list` 里已经有同名 server，用 `mcp update` 改参数，**不要新建重复的**。

### 4. 验证

1. `mcp list` 确认 `minimax-video` 存在且 enabled
2. `mcp get minimax-video` 看配置
3. 调 `describe_provider`，确认 `api_key_present = true`、`base_urls` 正确
4. 调 `list_video_models`，确认能列出视频模型

### 5. 真实出片验证（**会花钱，先问用户**）

用 `submit_video_generation` 提交一条**最短最便宜**的任务：

```
model=MiniMax-H3, duration=4, resolution=768P, ratio=16:9, prompt=一句话
```

- 提交前**必须**向用户确认这会产生计费调用
- 拿到 `task_id` 后用 `query_video_generation` 每 8 秒轮询，直到 `succeeded` 或 `failed`
- `succeeded` 时返回里会带 `local_path`（已自动转存到 `videos/`），确认这个 mp4 能播
- **失败不要自动重试**（已自动退款），要重试先问用户

## 工具契约（回归护栏，勿随意改名）

这些工具名与官方 `connector__matrix__*` 对齐，改名会让 Agent 侧的调用习惯断掉：

- `submit_video_generation(prompt, model, duration, resolution, ratio, input_image, last_frame_image, reference_images, reference_videos, reference_audios, callback_url)`
- `query_video_generation(task_id, model)`
- `list_video_tasks(page_num, page_size, status, model)`
- `list_video_models(keyword, video_only)`
- `regenerate_video_2k(source_task_id, base_video_url, resolution)`
- `delete_video_task(task_id)`
- `describe_provider()`

以下三个是本项目额外提供的（用来落实"三条铁律"）：

- `download_video(video_url, task_id)` —— 手动转存成片
- `list_local_tasks(status, limit)` —— 查本机台账（找回之前提交过的任务）
- `resume_pending_tasks(limit)` —— 续跑所有未到终态的任务

## 三条铁律（代码里已实现，不只是文档约定）

| 铁律 | 实现 |
| --- | --- |
| **一、task_id 立刻落库** | 提交**前**记一条「提交尝试」（`kind=attempt`），拿到 task_id **后**立刻写进台账 `.video-tasks.jsonl`。换会话后用 `list_local_tasks` / `resume_pending_tasks` 找回并续跑，**不必重新提交** |
| **二、终态不要自动重试** | 终态任务不进 pending，续跑跳过。**创建类请求（提交、升 2K）永不重试、永不换域名重发**（`allow_retry=False, allow_fallback=False`）—— 上游受理即计费，重试可能多出计费任务。提交失败会留下「未决提交」记录 |
| **三、直链拿到就转存** | 任务成功时**后台**下载成片到 `videos/`，台账里出现 `local_path`。不阻塞 MCP 调用（同步下载会堵死 server，客户端超时断连后 Agent 很可能重提 = 再扣一次钱）。失败会记进台账，续跑时重试 |

台账与成片目录都已在 `.gitignore` 里，是本地状态，不进仓库。

MCP server 启动时，如果台账里有未完成任务，会在 stderr 打一条提示 —— 看到它就先 `resume_pending_tasks`，别重新提交。

## 与 MiniMax 官方的九处差异（别对用户说"完全一致"）

中转站不是官方。这九处必须如实告知用户：

1. 不支持 `mm_file://`（素材只能公网 URL 或 `data:` 内联）
2. **不支持只传 `last_frame`**（必须与 `first_frame` 同传）
3. `POST /v2/h3_context_ir` **未接入，固定 400**
4. 多出 `1080P` / `4K`（官方 H3 只有 `480P`/`768P`/`2K`）
5. `usage` 只给秒数与图片数，**不给 token**
6. 报错 message 是中文，**末尾不带数字错误码**
7. `extra.prompt_expansion_mode` 只对 `MiniMax-H3-Max` 生效（官方亦然）
8. `DELETE` 只能删**已结束**的任务，处理中不能取消
9. 升 2K 仅 `model=MiniMax-H3` + `resolution=2K`，`source_task_id` 只认部分渠道出的 768P 成片

准确说法：**模型和参数与官方一致，接口行为有上述差异。**

## 禁止事项

- 不要让用户改 `provider.json`、`server.py` 或任何配置
- 不要把 key 打印到对话里、写进命令行参数、或提交到 git
- 不要在用户确认前发起任何**计费**的生成任务
- 不要因为任务失败就自动重试
- 不要尝试 `POST /v2/h3_context_ir`
- 不要只传 `last_frame` 而不传 `first_frame`
- 不要在实测发现行为与本文档不一致时**默默改代码** —— 先告诉用户差异

## 换厂商

改 `provider.json` 即可（端点、content 角色表、状态映射、规则）。
`provider.example.json` 是通用模板。适配层支持两种请求体形状：
有 `roles` 段 → content 数组（MiniMax 官方 V2）；没有 → 平铺字段。

## 自测

```bash
python -m unittest discover -s tests -t . -v
```

改动 `server.py` / `keyfile.py` / `provider.json` 后**必须**跑一遍，全绿才算完。
