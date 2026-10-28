# minimax-video-mcp

把 **MiniMax Code 的视频生成能力**接到第三方中转站上。

工具名、参数、调用流程与 MiniMax 内置的 `matrix` 视频连接器**完全一致**，
Agent（MiniMax Code / Claude Code / Cursor）侧的写法一个字都不用改。

> **你只需要做一件事：把 API Key 写进 `api.txt`。**
> 别的什么都不用改、什么都不用配。

---

## 三步接入

### 1. 拿仓库

```bash
git clone https://github.com/FlapPearLabs/minimax-video-mcp.git
cd minimax-video-mcp
```

### 2. 写 key

在中转站控制台「管理 API 密钥」创建一个 key，复制 `api.txt.example` 为 `api.txt`，
把 key 粘进第一行：

```bash
cp api.txt.example api.txt      # Windows: copy api.txt.example api.txt
```

```
sk-xxxxxxxxxxxxxxxx
```

格式很宽松，下面这些都能认出来（`#` 开头是注释）：

| 你可能写成这样 | 认不认 |
| --- | --- |
| `sk-abc123...` | ✅ 标准 |
| `Bearer sk-abc123...` | ✅ |
| `"sk-abc123..."` | ✅ 带引号 |
| `Authorization: Bearer sk-abc123...` | ✅ 整行粘 |
| `{"api_key": "sk-abc123..."}` | ✅ JSON |
| 文件里有多行 | ✅ 取第一个 `sk-` 开头的 |
| 末尾有空格 / 空行 / 换行符是 CRLF | ✅ 自动清理 |
| 文件开头有 BOM | ✅ 自动清理 |

### 3. 跑一条命令

```bash
python install.py
```

它会：检查环境 → 装依赖 → 读 key → **验证 key 能不能用**（只读，不花钱）→
列出你能用的视频模型 → 跑完整测试 → 打印出 MCP 注册参数。

看到「准备就绪」就成了。

---

## 注册到 MiniMax Code

`install.py` 最后会打印一段 JSON。**把它交给 Agent**，Agent 调用 `mavis` 工具即可完成：

```
mcp create
  name        = minimax-video
  transport   = stdio
  command     = python
  args        = ["<仓库绝对路径>/server.py"]
  description = 第三方中转站 MiniMax 视频生成
```

> `env` **不用传** —— `server.py` 会自己去读同目录的 `api.txt`。
> 想用环境变量的话，设 `VIDEO_API_KEY` 即可（优先级更高）。

注册完 `mcp list` 里能看到 `minimax-video` 就成了。

### 或者：直接把这段发给 Agent

仓库里的 [`接入提示词.md`](接入提示词.md) 是一段可以直接粘贴进 MiniMax Code 的提示词，
Agent 读完会自己完成克隆、读 key、注册、验证。你也可以直接说：

> 帮我把 https://github.com/FlapPearLabs/minimax-video-mcp.git 这个项目接进 MiniMax Code。
> key 在 api.txt 里。

> **要把这个项目分享给别人？** 看 [`给同学的说明.md`](给同学的说明.md) —— 里面有可以直接群发的文案，
> 和一段转发给同学自己 AI 助手的提示词。

---

## 提供的工具

| 工具 | 作用 | 对应官方 |
| --- | --- | --- |
| `submit_video_generation` | 提交异步任务 → 返回 `task_id` | `connector__matrix__submit_video_generation` |
| `query_video_generation` | 轮询 → `status` / `video_url` / `error` | `connector__matrix__query_video_generation` |
| `list_video_tasks` | 分页列任务 | — |
| `list_video_models` | 列站点上可用的视频模型 | — |
| `regenerate_video_2k` | 768P 成品升 2K | — |
| `delete_video_task` | 删除已结束的任务记录 | — |
| `describe_provider` | 适配器配置概览 + key 来源 | — |
| `download_video` | 手动把成片直链转存到本地 | — |
| `list_local_tasks` | 查本机台账，找回之前提交过的任务 | — |
| `resume_pending_tasks` | 续跑所有未到终态的任务 | — |

---

## 三条铁律（代码里已实现，不只是文档约定）

| 铁律 | 实现 |
| --- | --- |
| **一、task_id 立刻落库** | 提交成功即写入本地台账 `.video-tasks.jsonl`。换会话、换机器、隔天回来，用 `list_local_tasks` / `resume_pending_tasks` 就能找回任务，**不必重新提交**（重新提交 = 再扣一次钱） |
| **二、终态不要自动重试** | `failed` / `cancelled` 不会被自动重提，续跑时也会跳过。失败任务平台已自动退款，重试 = 再扣一次钱 |
| **三、直链拿到就转存** | 任务成功时自动把成片下载到 `videos/`，返回值和台账里都给 `local_path`。直链过期也不怕 |

台账 `.video-tasks.jsonl` 和 `videos/` 都在 `.gitignore` 里，是本地状态，不进仓库。

MCP server 启动时如果发现未完成任务，会在 stderr 打一条提示 —— 看到它就先 `resume_pending_tasks`，**别重新提交**。

---

## 站点接口

| 项 | 值 |
| --- | --- |
| Base URL | `https://api.lk888.ai`（备用 `https://ai778.cc/houduan`） |
| 鉴权 | `Authorization: Bearer sk-xxx`（兼容 `x-api-key` / `x-goog-api-key` / `?key=`） |
| 创建任务 | `POST /v2/video_generation` |
| 查询任务 | `GET /v2/query/video_generation/{task_id}` |
| 任务列表 | `GET /v2/query/video_generation?page_num&page_size`（≤50，仅近 7 天） |
| 删除任务 | `DELETE /v2/video_generation/{task_id}`（仅已结束的） |
| 升 2K | `POST /v2/video_regeneration` |
| 推荐模型 | `MiniMax-H3`（全形态，768P~4K，4~15 秒，2K 有声） |

请求体与 **MiniMax 官方 V2 逐字段同形**（`model` / `content[]` / `resolution` / `duration` /
`ratio` / `callback_url`），所以成片效果和走官方一致。

---

## 平台规则（提交前本地拦截，不白烧额度）

1. `resolution` 与 `duration` **必填**
2. 文生视频**必须**给具体 `ratio`，且**不能是 `adaptive`**
3. 图生视频 `ratio` 恒按 `adaptive` 处理
4. **只传 `last_frame` 会 400**，必须与 `first_frame` 同传
5. **帧模式与参考模式互斥**（`first_frame`/`last_frame` 不能与 `reference_*` 同传）
6. `POST /v2/h3_context_ir` 平台未接入，固定 400
7. 不支持 `mm_file://`；图片/音频可公网 URL 或 `data:` 内联；**视频只收公网 URL**
8. `failed` 任务**已自动退款**，不要重复提交
9. 轮询 **5~10 秒一次**；768P 通常 1~4 分钟，1080P/2K/4K 更久

这些写在 `provider.json` 的 `rules` 段，`server.py` 会在**发出请求之前**拦下违规组合。

---

## 跑测试

```bash
python -m unittest discover -s tests -t . -v
```

覆盖：key 解析的 30+ 种边界情况、content[] 组装、9 条平台规则、mock 端到端、
base_url 故障切换、真实 MCP stdio 协议握手、安装器行为、三条铁律的专项验证。

---

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `没找到 API key` | `api.txt` 不在仓库根目录，或第一行不是 key。`install.py` 会打印它要找的绝对路径 |
| `401` | key 抄错了，或用了 MiniMax 官方 key 而不是中转站的 key |
| `403 ip_not_allowed` | 控制台给本机 IP 设了白名单，把本机公网 IP 加进去或清空白名单 |
| `402` | 余额不足，去控制台充值 |
| `连不上` | 网络/代理问题；也可改 `provider.json` 的 `base_url` |
| `缺少依赖 mcp` | `python -m pip install -r requirements.txt`；被系统 Python 限制时用虚拟环境 |
| Agent 说工具没出现 | `mcp list` 确认已启用，然后重启/重载 MCP |
| 任务失败 | **已自动退款**。看 `task.error.message`（中文），不要自动重试 |

### 虚拟环境（推荐，避免系统 Python 限制）

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python install.py
```

---

## 安全

- `api.txt` 已在 `.gitignore` 里，**不要**提交、不要贴进聊天
- 密钥只走 `api.txt` 或环境变量 `VIDEO_API_KEY`，不进命令行参数
- 中转站会留存你提交的 prompt 和素材。公开素材走中转站没问题；工作文档、商业机密建议仍走官方直连

## 许可

MIT
