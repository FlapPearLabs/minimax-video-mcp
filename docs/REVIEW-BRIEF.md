# 对抗式代码审查简报：第三方视频 API 接入能否做到「与官方完全等价」

## 一、我们唯一在意的目标

把 MiniMax Code 的**官方视频能力**换成走第三方中转站（七七八AI），要求：

> **除了"请求发到哪个服务商"以外，其余一切与官方完全等价** ——
> 官方插件的工具面原样可用、官方 skills 原样能跑、
> **视频生成**和**视频修改（编辑）**功能一个不少、参数与返回结构一致。

这不是"做个差不多的替代品"，是"**换汤不换药**"。达不到就是达不到，请直说。

## 二、被审项目

- 仓库：https://github.com/FlapPearLabs/minimax-video-mcp （**你已经 clone 到自己的工作区**，审这个 clone）
- 形态：自建 MCP server（`server.py` + `provider.json` + `journal.py` + `keyfile.py`）
- 暴露的工具：`submit_video_generation` / `query_video_generation` / `list_video_tasks` /
  `list_video_models` / `regenerate_video_2k` / `delete_video_task` / `download_video` /
  `list_local_tasks` / `resume_pending_tasks` / `describe_provider`
- 上游：中转站 `https://api.lk888.ai`，走 **MiniMax 官方 V2 协议透传**（`POST /v2/video_generation`、
  `GET /v2/query/video_generation/{task_id}`）
- 附带的工程约束：创建类请求不重试（防重复扣费）、台账落库（防丢 task_id）、成片自动转存

## 三、官方侧的"标尺"就在本机（判断"一模一样"的唯一依据）

### 3.1 官方连接器工具面

跑 `mcode-tools connector tools` —— 共 19 个工具，其中 `matrix` provider 13 个。
视频相关三个：

- `connector__matrix__submit_video_generation`
- `connector__matrix__query_video_generation`
- `connector__matrix__videos_understand`

媒体相关十个：`generate_image` / `describe_images` / `search_images` / `reverse_image_search` /
`synthesize_speech` / `batch_text_to_audio` / `batch_text_to_music` / `get_voice_list` /
`listen_audio` / `audios_understand`

用 `mcode-tools connector tool <tool_name>` 看完整 `input_schema` / `output_schema`。

### 3.2 官方插件与 skills（本机 plugin-cache，**只读参考，不要改**）

- `C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-bc6973a2dce84af2e31eecbcb78e28d4b8dfd3ad79ae58cecef4f6779b74f304\`
  = **`minimax-video` 插件**。含 `servers.mcp.json`（声明了 `openchatcut` 这个 streamable-http MCP：
  *"读取视频工程、创建编辑草稿、剪辑时间线并提交审阅"*）、`skills/code-video`、`skills/lucid`、
  `miniapp/node/server.mjs`
- `C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-11421417a64d00605ec71d4d50200f6ea63e5b70f0e2e780fe9a5161d352e20a\`
  = **`minimax-h3-skills` 插件**。9 个 H3 skills：`brand-promo-video-generator` /
  `3d-animation-short-generator` / `co-op-game-intro-generator` / `h3-prompt-writing` /
  `handdrawn-live-video-generator` / `minimalist-product-ad-generator` /
  `music-video-subtitle-generator` / `paper-collage-explainer-generator` /
  `papercraft-stop-motion-explainer`
- 同目录下还有 `video-creater`、`everme` 等插件包，自己找

### 3.3 一条关键线索（务必自己查证，别信我这句话）

官方 H3 skills 的 `SKILL.md` 里列出了它们依赖的工具，例如
`hub_generate_video` / `hub_video_edit` / `hub_generate_image` / `hub_generate_audio` /
`hub_generate_music` / `hub_synthesize_speech` / `hub_analyse_media` /
`hub_canvas_get_node` / `hub_canvas_group_recent_outputs`，
且 frontmatter 明写：
*"Requires the MiniMax Hub agent (canvas workspace, choice cards, and
hub_generate_image/hub_generate_video tools); **not portable to generic agent harnesses**"*。

**但 `hub_*` 这套工具不在 `mcode-tools connector tools` 目录里。**
请自己查清：它们由谁提供（Hub agent？某个本地 MCP？插件的 miniapp？）、能不能换上游服务商、
官方 skills 是怎么被它们驱动的。

### 3.4 官方 V2 协议文档

- https://platform.minimax.cn/docs/api-reference/video-generation-v2-create.md
- https://platform.minimax.cn/docs/api-reference/video-generation-v2-query.md

### 3.5 中转站

`https://ai778.cc`（New-API 系聚合站），Base URL `https://api.lk888.ai`。
**允许**做免鉴权探测（期望返回 401，安全）：
`GET https://api.lk888.ai/v2/query/video_generation/1`、
`GET https://ai778.ai/v1/models` 等。

**禁止**使用或索取任何真实 API key；**禁止**发起任何计费的视频生成。

## 四、必须逐条回答的问题

### Q1 官方"视频能力"的完整边界是什么？

列出官方**视频生成** + **视频修改（编辑）**相关的全部工具 / 能力 / 入口，横跨四层：
连接器侧、插件侧（`servers.mcp.json` 声明的 MCP）、Hub agent 侧（`hub_*`）、skills 侧。

明确标注：哪些属于"换服务商后**应该原样保留**"的范畴。

### Q2 当前项目差在哪？

逐项对比 Q1 与被审项目。至少覆盖：

- **工具名是否逐字匹配**。官方是 `connector__matrix__*` 命名空间，被审项目是裸工具名。
  官方 skills / 官方文档引用的是哪一种？改完之后官方 skills 能不能**原样**跑起来？
- 缺哪些能力（视频理解？剪辑/工程/草稿/时间线？图片/语音/音乐？）
- 请求体、返回结构、状态机、错误语义与官方是否一致
- **"视频修改"这条线**：官方怎么做的？被审项目做了什么？差多少？

### Q3 有哪几条可行路线？

至少评估这四条（欢迎补充）：

- **路线 A**：直接把官方插件 / Hub 的上游 base_url 换成中转站。
  先查清 `hub_*` 由谁提供、能不能换上游。这条最"一模一样"，但可能要改官方安装物。
- **路线 B**：自建 MCP server，把工具名做成与官方**逐字一致**（含 `connector__matrix__*` 命名空间），
  并补齐缺失能力。
- **路线 C**：保留现在的实现，改官方 skills 里引用的工具名（批量替换），让它们调自建 MCP。
- **路线 D**：兼容 / 别名 + 路由层。

每条给出：改动点（具体到文件 / 配置）、工作量估计、风险与可维护性、
**对"与官方完全等价"的达成度**、以及"官方后续升级会不会被拖住"。

### Q4 明确判定

当前项目**能否**达到我们的要求？

不能 → 给出达到要求所需的**最小改动清单**（按优先级排序，每项标注证据与验收方式）。
能 → 指出剩余风险。

### Q5 下一步

我（用户）下一步该先做哪一件事？给一个明确的动作，不要"可以考虑…"。

## 五、约束

- **只读审查**：不要修改被审仓库的源文件，不要 push、不要建 PR。
  验证产物只放你自己的工作区 / 临时目录。
- **不要使用或索取任何真实 API key**，不要发起计费的视频生成。免鉴权探测（期望 401）允许。
- 每条结论要有证据：文件路径:行号 / 命令输出 / 官方文档链接。
- 区分「已确认」与「推断」。不确定就写不确定，不要编。

## 六、交付格式

```
## Q1 官方视频能力边界
## Q2 差距清单
## Q3 路线评估
## Q4 判定 + 最小改动清单
## Q5 下一步
## 未验证项
```
