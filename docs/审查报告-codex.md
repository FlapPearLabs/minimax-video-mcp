# 审查报告 · Codex（gpt-6.1-sol @ high）

> 对抗式代码审查，独立 clone、独立写探针，未使用真实 API key、未发起计费生成。
> 审查简报见 `docs/REVIEW-BRIEF.md`。

---

## Q1 官方视频能力边界

**判定：当前 HEAD 不满足“除服务商外，其余与官方完全等价”。** 已确认的障碍包括调用入口、媒体参数、资产返回结构和编辑能力；不是仅有工具名前缀不同。

审查对象为当前工作区 HEAD：`02527fdbd3cc6dfdc2838fddaa36aa38fb23257a`。本次未修改仓库源文件，未读取真实 key，未提交生成任务。

下文使用这些路径缩写：

- `R`：当前被审仓库。
- `V`：`C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-bc6973a2dce84af2e31eecbcb78e28d4b8dfd3ad79ae58cecef4f6779b74f304`
- `H`：`C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-11421417a64d00605ec71d4d50200f6ea63e5b70f0e2e780fe9a5161d352e20a`
- `G`：`C:\Users\ssy\.minimax\v2\plugin-cache\official\sha256-tree-v1-d5eb4dd4b33c732239d4e2989a2b8db62d99e95e45341373a4729fa03bb1d036`
- `C`：`D:\minimaxcode\MiniMax Code\resources\resources\mcode-tools\cli.mjs`

**1. 连接器侧**

视频相关入口为：

| 入口 | 能力与证据 | 核验状态 |
|---|---|---|
| `connector__matrix__submit_video_generation` | 创建视频任务。`G/skills/write-h3-prompts/references/generation-lifecycle.md:9–19,33–40,64–78` | 已确认官方文件引用；实时 schema 未取得 |
| `connector__matrix__query_video_generation` | 查询任务、成功后取得资产标识。上述文件 `:128–155,234–240` | 同上 |
| `connector__matrix__videos_understand` | 视频理解入口。本机 `app.asar` 内前端分类代码包含该名称及 `understand_video` 映射 | 已确认静态引用；实时 schema 未取得 |
| `mcode-tools upload-temp-url` | 上传本地媒体；视频参考返回带时长的对象。上述 lifecycle 文件 `:48–62` | 已确认官方流程 |
| `mcode-tools get_asset_url <node_id>` | 从资产节点取得符合用户下载设置的短期下载地址。上述文件 `:234–240` | 已确认官方流程 |

相关媒体工具还包括简报列出的 `generate_image`、`describe_images`、`search_images`、`reverse_image_search`、`synthesize_speech`、`batch_text_to_audio`、`batch_text_to_music`、`get_voice_list`、`listen_audio`、`audios_understand`。**本次没有成功取得实时目录，不能把“19 个工具、matrix 13 个”作为已独立核验的当前数量。**

实际执行了目录查询和三个视频工具的详情查询，均出现：

```text
error: MCode host authentication broker is unavailable. Open or restart the MCode host.
```

**2. 插件侧：视频编辑是独立系统**

已确认 `minimax-video` 插件声明了 `openchatcut` streamable-http MCP；它不是生成任务的另一种叫法。

- `V/servers.mcp.json:4–9`：声明“读取视频工程、创建编辑草稿、剪辑时间线并提交审阅”。
- `V/miniapp/miniapp.json:11–22`：miniapp 进程入口及 `/mcp/openchatcut` 端点。
- `V/miniapp/node/server.mjs:69–97`：装载编辑器运行时。
- `V/miniapp/node/runtime/editor.mjs:38990`：实际注册 `/mcp/openchatcut` 路由。

查到的工具和能力包括：

| 能力 | 工具实例／入口 |
|---|---|
| 工程绑定、读取与管理 | `target_project`、`read_project`、`list_projects`、`create_project` 等 |
| 草稿隔离、恢复与审阅 | `begin_edit_session`、`get_edit_session`、`list_edit_sessions`、`recover_edit_session`、`review_edit_session`、`discard_edit_session` |
| 时间线编辑 | `read_timeline`、`move_item`、`set_item_timing`、`split_item`、`duplicate_item`、`remove_item`、`edit_track`、`edit_item` |
| 字幕、转录和音频处理 | `edit_captions`、`transcribe_track`、`apply_script`、`normalize_loudness`、`isolate_voice`、音乐节奏分析与对齐 |
| 素材导入和画面检查 | `import_asset`、`import_assets`、`view_timeline_frames`、`view_asset_frames`、`probe_media`、`detect_scenes` |
| 可编辑动画与导出 | `create_motion_graphic_from_code`、`submit_export`、`track_export`、`verify_export`、`export_jianying_draft` |

证据：`V/miniapp/client/agent/openchatcut-tool-schemas.json`，例如 `:23,1024,3042,3099,4079,4226,4452,4502,5430`；草稿控制工具见 `V/miniapp/node/runtime/editor.mjs:2221`。该静态目录包含 **124 个 edit 条目、23 个 ask 条目**；这不是当前连接会话实际暴露数量，存在重复及运行时筛选。

**3. Hub agent 侧**

已确认 H3 工作流依赖：

```text
hub_generate_video
hub_video_edit
hub_generate_image
hub_generate_audio
hub_generate_music
hub_synthesize_speech
hub_analyse_media
hub_image_search
hub_audio_meta
hub_canvas_get_node
hub_canvas_group_recent_outputs
```

证据：`H/skills/brand-promo-video-generator/SKILL.md:4–18`。其中还依赖画布、选择卡、资产分组和 Agent 调度；不能把这些都归结为一个视频生成 HTTP 请求。

关于“由谁提供”：

- **已确认**：官方将这套能力归属于 MiniMax Hub agent／canvas 工作流；官方公开仓库也明确区分 Hub 专用的八个生产 skills 与可移植的提示词 skill。[官方 H3 仓库](https://github.com/MiniMax-AI/MiniMax-H3)
- **已确认**：被检查的 `openchatcut` 运行时没有 `hub_generate_video`／`hub_video_edit` 字符串；H3 插件文件声明依赖这些工具，没有提供其实现。
- **尚未确认**：Hub 实际注册器、完整 schema、执行服务及可替换服务商的配置入口。现有证据不足以认定它们由本地 miniapp 提供，也不足以认定改某个 `base_url` 就能接管。

**4. Skills 侧**

| Skills | 实际驱动方式 |
|---|---|
| `video-creater/write-h3-prompts` | 明确走 `mcode-tools Connector`，包含上传、提交、后台轮询、Drive 资产和下载交付 |
| 八个 H3 生产 skills | 依赖 Hub 画布和原生生成／编辑工具 |
| `h3-prompt-writing` | 纯提示词整理，可移植，无外部 API 调用；它能运行不能证明视频接入兼容 |
| `code-video` | 创建可编辑 JSX 动画，放入编辑草稿，抽帧检查、审阅、导出 |
| `lucid` | Python 代码渲染 MP4，再导入编辑器、审阅和导出 |

证据：`G/.../generation-lifecycle.md:3–22`；`H/skills/h3-prompt-writing/SKILL.md:3–14`；`V/skills/code-video/SKILL.md:8–15`；`V/skills/lucid/SKILL.md:8–23`。

按本次目标，**上述视频入口及生产流程依赖都应原样保留**。图片、语音、音乐等可以复用原有官方能力，不必全部重写，但不能让换视频服务商破坏它们。另查到 `everme` 是个人长期记忆插件，不属于视频能力提供方：其 `.minimax-plugin/plugin.json:3–20` 明确如此。

## Q2 差距清单

**P0：调用路径不兼容，改名也不充分。**

当前实际导出的十个工具全部是裸名，没有 `connector__matrix__*`，没有 `hub_*`，没有编辑器工具。证据：`R/server.py:661–675,804–805,1007–1207`；临时验证的 [工具清单及 schema](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/mcp-schema.json)。

更关键的是，官方 skill 不仅在文字中引用全名，还执行：

```text
mcode-tools connector call connector__matrix__submit_video_generation ...
```

其 CLI 使用官方云端 `/minimax-cloud/api/v1/connectors/connected-tools/list` 和 `/minimax-cloud/api/v1/connectors/tools/call`，按 `runtime_tool_name` 查找工具。**注册同名本地 MCP 不会自动接管这条路径。**

证据：`G/.../generation-lifecycle.md:3,71,128`；`C:23234–23260,23320–23325`。

此外，宿主可能再给 MCP 工具加命名空间；线上的工具名也必须验证，不能只改 Python 函数名。

**P0：请求参数不是“同形”。**

| 对比项 | 官方文件约定 | 当前实现／影响 |
|---|---|---|
| 媒体输入 | HTTPS URL 对象；视频参考对象包含时长信息 | `input_image: str`，参考素材为 `List[str]` |
| 模式选择 | `reference_type="first_frame"／"last_frame"／"subject"` | 没有 `reference_type` 参数 |
| 尾帧生成 | `input_image` 配合 `reference_type="last_frame"` | 无此入口；仅传 `last_frame_image` 被明确拒绝 |
| 模型分支 | 官方 skill 包含 H2.3 的独立参数规则 | 统一走 H3 V2 组装及全局 4～15 秒规则，没有对应兼容分支 |

证据：`G/.../generation-lifecycle.md:24–42,48–62`；`R/server.py:266–285,308–328,359–362,662–675`；`R/provider.json:87–98`。

独立复现：传入媒体对象给组装函数得到：

```text
AttributeError: 'dict' object has no attribute 'startswith'
```

这是内部组装层的验证；通过 MCP schema 调用时，媒体对象还可能更早被字符串类型校验拒绝。两者均不能原样接受官方文件要求的输入。[复现输出，第 3～4 行](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/contract-evidence.txt:3)

**P0：返回状态名称部分接近，资产和返回结构不同。**

- 当前查询返回顶层 `task_id/status/video_url/raw_status/model`，再添加本地下载信息。
- 官方 skill 成功流程要求 `node_id`、`file_name`，随后调用 `get_asset_url`；明确把成功但没有 `node_id` 视为交付未验证。
- 当前没有创建官方 Drive／Hub 节点的逻辑，也没有该资产下载契约。
- 当前还不保持官方原始 V2 的 `task` 对象；时间戳、分辨率、时长、比例、任务类型等字段没有完整返回。

证据：`R/server.py:794–800,840–889`；`G/.../generation-lifecycle.md:152,217,234–240`；[官方 V2 查询响应](https://platform.minimax.cn/docs/api-reference/video-generation-v2-query)。

`queued/running/succeeded/failed/cancelled` 这些终态名称基本对齐，不代表完整状态机及副作用等价。当前额外归一化状态，并在成功后后台下载；官方 skill 文件描述的成功查询还有保存 Drive 资产的行为。证据：`R/provider.json:63–74`、`R/server.py:482–486,875–889`、`G/.../generation-lifecycle.md:152`。

**P0：视频理解、编辑工程和 Hub 编排没有实现。**

当前十个工具中没有视频理解、草稿、时间线、字幕编辑、画布节点、选择卡及导出工具，也没有调用它们的桥接层。

`regenerate_video_2k` 只发送视频再生成请求，不能替代：

1. H3 根据参考视频和提示词进行的生成式修改；
2. Hub 的 `hub_video_edit` 编排；
3. OpenChatCut 对已有工程的确定性剪辑与审阅。

参考视频可以进入当前生成请求，但这只能证明“能组装参考视频输入”，不能证明编辑能力及返回契约等价。证据：`R/provider.json:45–50`、`R/server.py:1111–1180`，与 Q1 的编辑工具清单对照。

**P1：错误语义未兼容。**

HTTP 错误被转换为截断响应文本的 `RuntimeError`，没有保留结构化的官方错误包；任务错误则重新组装成 `{code,message}`。官方 CLI 另有 `is_error/error_code/error_message/provider_usage_json` 外层契约。不能据此宣称返回结构一致。

证据：`R/server.py:213–223,851–859`；`C:23185–23193,23334–23338`。官方 V2 错误格式包含 `error.type/http_code` 和 `request_id`。[官方创建接口](https://platform.minimax.cn/docs/api-reference/video-generation-v2-create)

**P1：平台能力差异不能靠别名消除。**

- 官方文件支持尾帧模式；当前配置主动禁止。
- 官方 V2 支持 `mm_file://`，当前 `_media_value` 会按本地路径处理。
- 官方公开 H3-Context-IR 接口；当前没有对应工具或端点。
- 官方 DELETE 可以取消排队任务；当前项目声明只支持删除终态任务。没有实测中转站取消能力，不能断言它当前必定拒绝。

证据：`R/server.py:266–279,359–362,1183–1203`、`R/provider.json:122–143`；[官方创建接口](https://platform.minimax.cn/docs/api-reference/video-generation-v2-create)、[Context-IR 接口](https://platform.minimax.cn/docs/api-reference/video-generation-v2-h3-context-ir)、[取消或删除任务](https://platform.minimax.cn/docs/api-reference/video-generation-v2-delete)。

实时官方创建文档还已列出 H3 Highspeed／Lite。当前模型名可以透传，但没有模型级参数规则，不能把“未禁止这个字符串”当成支持证明。验证中 H3-Max 的 `4秒 + 2K` 仍被组装通过，与当前官方规格冲突。[复现输出，第 5 行](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/contract-evidence.txt:5)

**P1：附带工程约束仍有漏洞。**

| 已确认问题 | 影响及证据 |
|---|---|
| 分页被覆盖 | `list_video_tasks(3,7)` 实际发送 `1/20`。`server.py:1027–1033` 后写配置覆盖调用参数；`provider.json:126` 固定值。[复现输出，第 8 行](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/contract-evidence.txt:8) |
| 升 2K 没有提交前 attempt | `_request` 在台账写入前执行；模拟“受理后超时”没有未决记录。`server.py:1147–1168`。[复现输出，第 9 行](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/contract-evidence.txt:9) |
| 普通提交前台账失败仍继续 | `record()` 可返回 `None`，提交前未检查，之后照常发 POST。属于已确认控制流；本次未做该故障注入。`journal.py:82–124`；`server.py:721–743` |

创建和升 2K 的“不重试、不换域重发”确实实现了：`server.py:736–742,1147–1153`。但这不能补足上述记录缺口。

**测试结果不能证明官方兼容。**

临时副本运行原测试：

```text
Ran 146 tests in 237.901s
OK (skipped=2)
```

两项因副本没有 `.git` 跳过；原仓库另以 `git check-ignore` 确认 key、台账和视频目录被忽略。[测试日志](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/suite.log:244)

测试中的 `OFFICIAL_TOOL_NAMES` 实际写的是两个裸名，没有读取官方 schema，因而会放过命名不兼容。证据：`R/tests/test_mcp_protocol.py:21–25`。

## Q3 路线评估

以下工作量是**推断性估计**，按一名熟悉项目的工程师计算；不包含等待官方开放接口的时间。

| 路线 | 具体改动点 | 工作量、风险及维护性 | 对严格目标的达成度／升级影响 |
|---|---|---|---|
| **A：替换官方上游** | 找到 Connector 和 Hub 真正的生成适配器，只替换提供商请求层；保留编辑器、资产系统和 skills。不能把 `V/servers.mcp.json` 的编辑 MCP 地址改成视频 API 地址 | 入口核查约 1～3 人日；若有稳定扩展点再估实施。目前 Hub 替换入口未确认。改官方安装缓存容易被升级覆盖 | **理论最接近目标，当前不可宣称可落地。** 修改 CLI 的 API 地址也不等于换 V2：其调用的是官方云端连接器路径。证据：`C:23234–23255` |
| **B：自建完全兼容 MCP** | 改 `server.py` 的名称、输入输出 schema、媒体对象及模型分支；补资产桥接、理解能力；保留／接入 OpenChatCut；还需让官方 CLI 和 Hub 真正路由到它 | 生成契约适配约 2～4 人周；全栈兼容至少数人月，且受未公开运行时限制。接口面大，长期需跟进官方变更 | **单独同名 MCP 无法达标。** 即使 wire name 一致，也接管不了既有 CLI 云端路径。官方升级持续带来同步负担 |
| **C：修改官方 skills** | 在自有副本修改 `G/.../generation-lifecycle.md` 及轮询／下载脚本；八个 H3 skills 还需改画布、编辑、选择卡和资产流程 | 限定生成流程约 3～7 人日；完整生产流程需数周以上。不能只批量替换名称 | **不满足“官方 skills 原样运行”。** 属于分叉工作流；上游升级需要持续合并 |
| **D：兼容／别名＋路由层** | 保留官方插件和 skills；在宿主分发层同时接住 Connector 调用、CLI 调用及 Hub 视频生成调用；只把对应请求送进现有适配器，资产注册回原系统 | 若有官方扩展点，原型约 1～2 周、完善适配约 4～8 周；没有扩展点则仍是宿主分叉，无法给可靠工期 | **最合理的条件性架构。** 稳定 hook 下维护成本较低；私有补丁下同样会被官方升级拖住 |

**建议优先验证 D 所需的宿主路由入口，其次判断 A。** 两者都必须先拿到真实运行时契约。B 可以成为适配器的一部分；C 只能在用户接受改变目标后成立。

即使路由成功，中转站若确实缺失某项能力，也仍不能达到完全等价。不能用自动补造首帧、伪造 `node_id`、编造 token usage 等方式补齐差异。

## Q4 判定 + 最小改动清单

**不能。当前项目可定位为“第三方视频任务 MCP 适配器”，不能验收为“官方视频能力的透明替换”。**

`README.md:5–6` 的“工具名、参数、调用流程完全一致，一个字不用改”，已被上述命名、调用路径、媒体对象和资产流程证据否定。

达到目标至少需要以下改动。它们是**必要条件，尚不是已证明充分的实施清单**：

| 优先级 | 最小必要改动 | 证据与验收方式 |
|---|---|---|
| **P0** | 固定官方版本，导出 Connector、Hub 和编辑 MCP 的真实契约，建立兼容基线 | 当前 CLI 查询失败；静态文件不能代替实时 schema。验收：记录实际工具名、输入输出、错误及资产副作用 |
| **P0** | 建立真正接管调用的宿主路由，而非仅注册别名 | `C:23234–23260`；官方 skill 的 CLI 调用。验收：原样 skill 的提交和轮询均进入假提供商，官方生成出口没有被调用 |
| **P0** | 对齐媒体对象、`reference_type`、模型分支、响应和错误契约 | `G/.../generation-lifecycle.md:24–62,234–240` 对照 `server.py:662–675,840–889`。验收：官方输入样例及失败样例做契约差分测试 |
| **P0** | 接回真实 Drive／Hub 资产生命周期 | 官方流程依赖 `node_id`，当前只有 URL／本地路径。验收：原样 `get_asset_url` 及画布取货流程可用，不伪造标识 |
| **P0** | 保留 OpenChatCut 编辑、Hub 编排及相关媒体能力 | Q1 中已确认工具与 skills。验收：现有素材完成导入→草稿修改→审阅→应用→导出；Hub 流程保留画布和分组 |
| **P0** | 解决提供商功能硬缺口，或明确承认不能通过严格验收 | 尾帧模式已被本地禁止；其他平台限制尚需证实。验收：官方有效场景逐项可用，不能靠改变用户输入绕过 |
| **P1** | 修复分页、升 2K attempt、提交前记录失败仍放行及模型校验 | Q2 已给出代码和复现。验收：分页透传正确；受理后超时可追踪；记录失败时不发创建请求 |
| **P1** | 更换兼容性回归测试和不实说明 | 现有测试自定义了裸名“官方标准”。验收：从官方契约生成测试，明确分别报告生成、资产、编辑、Hub 的结果 |

## Q5 下一步

**先在正常运行的 MiniMax Code／Hub 环境完成一次只读“官方契约与路由入口导出”。暂时不要改工具名。**

本次具体阻塞是 MCode host authentication broker 不可用。恢复宿主后，导出：

```text
mcode-tools connector tools
mcode-tools connector tool connector__matrix__submit_video_generation
mcode-tools connector tool connector__matrix__query_video_generation
mcode-tools connector tool connector__matrix__videos_understand
```

同一次核查必须定位 Hub 的 `hub_generate_video`／`hub_video_edit` 注册及服务商路由入口。**验收产物是 schema 和可替换入口的证据，不是一次付费出片。** 这一步决定 A／D 能否成立；没有它，继续补自建 MCP 很可能补不到官方实际调用的位置。

## 未验证项

- **官方实时目录与 schema**：目录及三个详情命令均报 broker 不可用。未独立确认简报所述工具数量，也未完成实时 schema 逐字段差分。
- **Hub 的实际实现位置及可配置性**：已确认官方声明的运行环境归属；没有找到足以证明可替换上游的注册器或配置。不能宣称已查明其内部服务。
- **OpenChatCut 当前运行会话**：核对了声明、静态工具目录和运行时代码，未启动编辑器验证实际工具暴露、草稿应用及导出。
- **中转站鉴权后行为**：没有使用真实 key。主查询端点仅做无鉴权 GET，返回 `401` 和 `missing_api_key`；这不证明模型、生成、退款或编辑能力。[探测记录](C:/Users/ssy/AppData/Local/Temp/minimax-review-30d17622ec4c41e381157e0fba701a6c/public-probe.txt:1)
- **备用探测域名**：简报中的 `ai778.ai` 本次 DNS 解析失败；不能据此判断 `ai778.cc` 或主服务故障。
- **平台九处差异**：没有把项目文档的全部陈述当作已实测事实。例如退款、1080P／4K、Context-IR 固定 400、升 2K 渠道限制均未验证，也未调用禁止探测的接口。
- **生成质量和实际成片**：完全未验证。此次本地测试使用假服务／模拟响应，不能外推成生产可用或官方完全等价。
- **只读约束**：审查结束时 `git diff` 为空；状态仍只有开始时已有的未跟踪 `REVIEW-BRIEF.md`、`REVIEW-PROMPT.txt`。验证产物均在临时目录，未 commit、push 或创建 PR。
