---
name: video-maker-production
description: Run or resume videoMaker's provider-neutral long-video workflow in Antigravity, with explicit content/image generation methods and cross-agent handoff when required.
---

# Antigravity 长视频制作

在本仓库中创建或恢复长视频项目时使用本 skill。`project.json.providers` 是项目
provider 的唯一事实源，run 只使用 `state.json` 中的完整快照。不得增加阶段覆盖、
改写旧快照或在失败时切换 provider。

所有 Python 命令使用：

```bash
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

## 创建与恢复

1. 开始新项目前，先让用户分别选择两类生成方式，不要只报底层值：
   - 内容生成：`codex` = Codex 当前会话，`deepseek` = DeepSeek API，
     `antigravity` = Antigravity 当前会话。
   - 图片生成：`imagegen` = Codex 内置 ImageGen，`wanxiang` = 万相 API，
     `antigravity` = Antigravity 内置生图。
   Agent 是执行工作流与调用工具的环境，不等同于项目的 LLM 选择。
   用户已经明确选择时不重复询问。
2. 将两项选择同时传给
   `pipeline/workflow.py create --project <id> --llm <name> --image <name>`。
   新项目不得省略任何一项。LLM 和图片 provider/model 创建后永久固定；需要其他
   组合时创建新项目。
3. Antigravity LLM 跟随当前会话模型，Antigravity 图片使用平台内置生图工具；
   两者都不得传 model 参数，也不得调用 `agy`、Gemini API 或 Antigravity SDK。
4. `create` 后向用户回显两类生成方式的完整名称。若选择
   `--llm antigravity --image imagegen`，明确说明内容在 Antigravity 完成，
   图片阶段需切换到 Codex。工作流不会自动启动或调用另一个 Agent。
5. 新 run 执行 `pipeline/workflow.py init --project <id>`；恢复时先执行
   `pipeline/workflow.py status <run_id> --project <id>`。读取 `AGENTS.md`、项目
   `project.json`、`input/topic_request.md`、角色库和命令帮助，只使用状态输出的路径。

## Provider 路由

- 只有 `state.json.providers.llm.name == "antigravity"` 时，才由当前 Antigravity
  会话创作 topic、copy、script、storyboard、brand 或 publish 候选。
- 只有 `state.json.providers.image.name == "antigravity"` 时，才调用 Antigravity
  内置生图工具。若选择 `imagegen`（Codex 内置 ImageGen），应保留
  密封图片任务给 Codex，不得在 Antigravity 中用其他生图工具代替；若选择 DeepSeek/万相，
  只在用户授权对应外部调用后运行工作流命令。
- 任一 provider 失败时保存已有状态并只恢复当前 provider，不自动回退或混用来源。

## 内容任务包

1. 执行 `pipeline/workflow.py run <run_id> <stage> --project <id>`，其中 stage 为
   `topic`、`copy`、`script` 或 `storyboard`。
2. 读取状态输出指向的 `workflow/runs/<run_id>/tasks/<stage>.json`，严格满足其中
   `output_contract`，且只写 `candidate_path`。不得把聊天回复当成候选交付。
3. topic 输出三个候选且 `selected_id` 初始为 null；用户选择后才执行
   `select-topic`。topic 校验并提升后，如果 run 尚未选择内容模板，执行
   `template-options`；由 Sol 根据正式选题推荐一个模板、说明理由并展示全部选项。
   只有用户明确选择后才执行 `select-template`，不得静默采用默认模板。script 是
   Azure 与字幕唯一文本源，不得把 copy 机械改写为口播。
4. storyboard 必须逐块逐拍覆盖 script，每句按顺序恰好覆盖一次；不得加入
   provider、model、final prompt、negative prompt 或 API 请求字段。
5. 写候选后执行 `verify`。修复全部问题并向用户展示摘要；只有用户明确确认后才执行
   `promote`。分镜必须先 `verify storyboard`，再运行并校验 `storyboard-review`；用户
   确认后只提升 `storyboard`，由该命令同时锁定哈希匹配的审核记录。不得先提升正式
   分镜再审核。一次只推进一个需要人工确认的阶段。

## Antigravity 图片任务

1. storyboard 候选审核通过并由用户执行 `promote storyboard` 后，正式分镜与
   storyboard-review 会一起提升；此后才能执行 `run <run_id> images`。工作流每次只
   签发 `image_tasks.json` 中 `image_generation.active_key` 对应的一张密封任务。
2. 只使用签发任务的 `generation_request`：原样采用 `prompt`、`negative_prompt`、
   `size` 和 `reference_images`。`additional_prompt_allowed` 必须为 false；不得追加、
   删减或强化任何提示，不得自行并发领取后续任务。
3. 使用 Antigravity 内置生图工具生成一张图片，保存为该任务的 `output_path`。必须为
   可完整解码的 16:9 PNG；有参考图时必须全部传入，不得退化为纯文本生成。
4. 再次运行 `run <run_id> images` 让状态机校验文件和哈希，然后才领取下一张。新项目
   首次只生成首图；由用户确认并执行 `select-image-anchor` 后才能生成余图。
5. 全部候选落盘后执行 `verify images` 和 `run image-review`，检查语义、角色一致性、
   文字克制、字幕安全区、构图和风格。只有用户明确确认后才提升 images/image-review。

## V4 发布准备

- 发布文案与封面是两个独立子流程，可以并行生成、验证和提升；不得把封面字段写回
  copy 子产物，也不得在任一子产物未提升或 hash 过期时执行 `publish-finalize`。
- 封面模板必须先展示注册表选项，由 Sol 基于正式 topic 推荐，再由用户明确选择并
  锁定；没有默认模板，推荐与最终选择可以不同。
- “执行/测试完整发布流程”不是人工选择或提升授权。Antigravity/Codex 在模板选项、
  标题候选、两张封面候选及 verify 结果出现后必须分别停止；只有用户最新回复明确给出
  对应模板 ID、标题 ID、封面 ID 或确认提升时，才能执行相应 select/promote。Agent
  不得替用户选择、把自身审核当作用户确认，或一次性越过多个门禁并 finalize。
- `reference_006_v1` 使用正式场景锚点与必要角色；`book_title_author_v2` 使用正式场景
  参考锁定正片画风，以完整书名标签和一个痛点或反常识观点作为文字层级；本地排版
  采用居中书名铭牌、金色观点大字与0–14字白色解释副标题，主体位于文字下方；不展示作者，
  可选用至多一个正式角色，并采用全画幅电影海报式构图而非左右分栏。所有模板
  都沿用视频 run 固定的图片 provider，交互式 provider 逐张消费密封任务，不增加阶段
  provider 覆盖。
- 封面方向尚未稳定或用户需要多轮视觉打磨时，先使用 `cover-design-lab` skill，在项目
  `experiments/cover_templates/{lab_id}/` 下隔离探索。Cover Lab 不限迭代轮次，必须累计
  记录喜欢、否决和下一轮约束；不得创建 publish ID、修改发布状态或把实验图视为正式资产。
  Cover Lab V1 仅支持 `book_title_author_v2`；其他模板继续走原正式路径。
  用户明确确认后才可冻结设计包。正式发布锁定同一模板后，可用
  `publish-cover-import-design --lab-id ...` 原样导入冻结方向；此后只允许景别、构图、主体姿态
  和光线的受控变体，不得重新发明钩子、视觉隐喻或核心概念。
  用户选定正式发布标题后，还须执行 `publish-cover-title-check`，记录标题与封面钩子如何
  形成互补悬念并绑定 copy/cover plan hash；缺失或过期时不得提升导入的 Cover Lab 封面。
- 当图片 provider 为 `imagegen` 时，Antigravity 在写完 copy 或 cover plan 候选后必须
  立即停止并交还用户切换到 Codex；不得执行 `publish-cover-generate`、调用任何生图
  工具、伪造 PNG 或继续 compose/review/select/promote/finalize。该命令会检查 Codex
  会话标记，不在 Codex 环境时应把门禁错误原样报告给用户。
- 模型只写封面语义方案；书名、作者及其他关键文字由确定性本地合成写入。两个候选都
  必须留下模板定义的视觉审核记录，最终只允许选择审核通过的候选。

图片必须是连续全屏构图，不预留字幕栏或底部空带。允许语义必要且少量的场景内短文字、
数字或价格，但禁止段落、密集 UI、乱码、字幕和水印；底部中央不得放关键面部或不可遮挡
信息。`kind=phase_title` 时必须把 `title_text` 逐字生成在真实物体或建筑表面，不能做成
悬浮标题、标题卡、横幅或下三分之一字幕。

## 生产安全

- script 提升后 voice 与 storyboard 分支可以并行；images 与 voice 完成后才运行
  render，随后运行 qa。
- 已有正式成片时使用隔离 review 或新 revision，不覆盖历史成片。
- 不发布、不购买、不删除正式资产，不伪造来源；密钥不得写入配置、状态或日志。
- 额度或工具中断时报告未完成 task key，从状态与缺失候选续跑，不重复已通过项。
