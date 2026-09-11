---
name: video-maker-production
description: Run or resume videoMaker's provider-neutral long-video workflow in Antigravity, including Antigravity LLM task packets and serial built-in image generation.
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

1. 开始新项目前，先让用户分别选择 LLM provider：`codex`、`deepseek` 或
   `antigravity`；图片 provider：`imagegen`、`wanxiang` 或 `antigravity`。
   用户已经明确选择时不重复询问。
2. 将两项选择同时传给
   `pipeline/workflow.py create --project <id> --llm <name> --image <name>`。
   新项目不得省略任何一项。LLM 和图片 provider/model 创建后永久固定；需要其他
   组合时创建新项目。
3. Antigravity LLM 跟随当前会话模型，Antigravity 图片使用平台内置生图工具；
   两者都不得传 model 参数，也不得调用 `agy`、Gemini API 或 Antigravity SDK。
4. 新 run 执行 `pipeline/workflow.py init --project <id>`；恢复时先执行
   `pipeline/workflow.py status <run_id> --project <id>`。读取 `AGENTS.md`、项目
   `project.json`、`input/topic_request.md`、角色库和命令帮助，只使用状态输出的路径。

## Provider 路由

- 只有 `state.json.providers.llm.name == "antigravity"` 时，才由当前 Antigravity
  会话创作 topic、copy、script、storyboard、brand 或 publish 候选。
- 只有 `state.json.providers.image.name == "antigravity"` 时，才调用 Antigravity
  内置生图工具。若选择 Codex/ImageGen，应保留任务给 Codex；若选择 DeepSeek/万相，
  只在用户授权对应外部调用后运行工作流命令。
- 任一 provider 失败时保存已有状态并只恢复当前 provider，不自动回退或混用来源。

## 内容任务包

1. 执行 `pipeline/workflow.py run <run_id> <stage> --project <id>`，其中 stage 为
   `topic`、`copy`、`script` 或 `storyboard`。
2. 读取状态输出指向的 `workflow/runs/<run_id>/tasks/<stage>.json`，严格满足其中
   `output_contract`，且只写 `candidate_path`。不得把聊天回复当成候选交付。
3. topic 输出三个候选且 `selected_id` 初始为 null；用户选择后才执行
   `select-topic`。script 是 Azure 与字幕唯一文本源，不得把 copy 机械改写为口播。
4. storyboard 必须逐块逐拍覆盖 script，每句按顺序恰好覆盖一次；不得加入
   provider、model、final prompt、negative prompt 或 API 请求字段。
5. 写候选后执行 `verify`。修复全部问题并向用户展示摘要；只有用户明确确认后才执行
   `promote`。一次只推进一个需要人工确认的阶段。

## Antigravity 图片任务

1. storyboard 与 storyboard-review 提升后执行 `run <run_id> images`。工作流每次只
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
