# Repository Guidelines

## Model routing

在 Codex 运行环境中仅使用 Sol 和 Luna：Sol 主控、创作与工程判断，Luna 按需执行明确任务。
当项目选择 `llm=antigravity` 时，本节的 Codex 内部模型路由不适用，由 Antigravity
当前会话模型按工作区 skill 执行；不得把 Antigravity 会话模型伪装成 Codex 模型。

- 默认主控为 `gpt-6-sol`，推理强度为 `medium`；负责需求沟通、任务包、内容创作、架构设计、工程实现、复杂调试、调度与最终验收。仅在任务确有需要且运行环境支持时提高推理强度，不默认使用高强度推理；不得声称配置文件修改已热切换当前会话模型。
- `topic`、`copy`、`script`、`storyboard` 的新候选与任何主题、论点、叙事、案例、口播或镜头语义的实质修订均由 Sol 主控直接完成，不再为这些阶段例行启动另一个 Sol 子代理。`script` 仍是独立创作，不得作为 `copy` 的机械转写。
- Sol 读取正式输入、任务包与契约后，产出满足 `output_contract` 的完整候选或冻结修订稿。Sol 主控可写文件、运行命令和执行验证；这些操作不受可选只读咨询角色的限制。
- `luna_executor` 使用 `gpt-6-luna` / `low`，仅接收输入、修改范围、预期结果和验证方法均明确的任务。适合批量落盘、格式化、语法检查、`verify`、单测、渲染、重复检查以及方案确定的小改，不得自行补充需求或重新设计。
- 内容委派采用“Sol 创作与冻结 → Luna 原样落盘与验证 → Sol 验收”。Luna 只能修复不改变语义的格式问题；语义、叙事、画面或质量问题退回 Sol。工程接口、状态、契约或跨模块问题也交给 Sol 判断，不得为通过测试而放宽标准。
- 小任务、短候选落盘、单次命令及强依赖当前上下文的工作由 Sol 直接完成。只有执行量足以抵消交接成本时才调用 Luna，不为每个阶段强制增加代理轮次。
- 委派只传必要输入、路径、冻结结果和验收要求，避免复制整段对话、重复创作或重复校验；执行代理返回简短摘要、验证结果与阻塞，不回传无关完整日志。同一时刻最多一个专用子代理，子代理不得继续委派。
- `sol_architect` 保留为 `gpt-6-sol` / `high` 的可选只读独立复核角色，仅在用户明确要求独立复核时使用；普通创作、架构与调试均由 Sol 主控直接处理。
- 不调用 Astra、Terra 或其他主控/执行模型，也不自动升级到它们。Sol 不可用时暂停需要创作或判断的工作并说明；Luna 不可用时由 Sol 执行必要机械步骤。
- `select-topic` 由用户选择后执行，候选资产仍须用户明确确认后方可 `promote`；模型分工不改变人工选择与提升边界。
- 上述模型分工属于 Codex 内部代理路由，不改变项目的单一 LLM provider 与单一图片 provider 配置，也不得增加阶段 provider 覆盖。
- 无论由哪个模型执行，破坏性操作、外部发布、密钥使用和候选资产提升仍遵循本文件的授权与安全规则。

## Structure

- `pipeline/workflow.py`：唯一 provider-neutral 编排入口。
- `pipeline/workflow_contracts.py`：四阶段 schema、校验、ImageTask 组装。
- `pipeline/providers/`：LLM registry（Codex/DeepSeek/Antigravity）与图片 registry（ImageGen/万相/Antigravity）。
- `pipeline/build_long.py`：公共字幕、运镜、SFX、BGM、1080p 渲染。
- `pipeline/tts_azure.py`：唯一 TTS；Azure 内重试，不允许跨语音服务回退。
- `pipeline/migrate_provider_architecture.py`：V5 旧项目一次性迁移工具。
- `projects/{id}_书名/`：`project.json`、`input/` 正式契约、`workflow/runs/` 状态、候选区、图片/音频/输出。

根目录不得保存项目数据。项目 id 由 `--project` 或 `PROJECT` 解析，id 在目录重命名时保持不变。

## Commands

所有 Python 命令使用：

```bash
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pipeline/workflow.py create --project 003 --llm codex --image imagegen
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pipeline/workflow.py init --project 003
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pipeline/workflow.py run <run_id> <stage>
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pipeline/workflow.py verify <run_id> <stage>
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pipeline/workflow.py promote <run_id> <stage>
/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -v
```

## Contracts and state

- 面向用户时使用“内容生成方式”和“图片生成方式”，不把 Agent 工具与 LLM
  provider 混为同一概念。`codex` 表示 Codex 当前会话，`deepseek` 表示
  DeepSeek API，LLM `antigravity` 表示 Antigravity 当前会话；`imagegen`
  表示 Codex 内置 ImageGen，`wanxiang` 表示万相 API，图片 `antigravity`
  表示 Antigravity 内置生图。底层配置键和值保持不变。
- 每次开始新视频项目时，必须先确认内容生成方式（`codex`/`deepseek`/`antigravity`）
  和图片生成方式（`imagegen`/`wanxiang`/`antigravity`），并同时传给
  `create --llm --image`；不得依赖静默默认值。两者落在不同 Agent 环境时，
  创建结果和交付摘要必须明确说明切换时机。
- 一个项目只能配置一个 LLM 和一个图片 provider；两者及其模型配置在创建时选定后永久固定，完成后也不切换；需要另一种组合时新建项目。不得增加阶段覆盖参数或修改已有 run 快照。
- `state.json` 必须保存 `project.json.providers` 的完整快照。
- `docs/used_books.md` 汇总已提升的正式选题书目；每次提升 topic 后自动更新。
  新 topic 任务包必须附带跨项目已用书单，候选不得重复已用书目；校验和提升都要拦截重复。
- 新项目未显式指定内容模板时不得采用默认模板。topic 选择、校验并提升后，由 Sol
  根据正式选题推荐模板并展示全部选项；只有用户明确选择并执行 `select-template` 后
  才能解锁 copy。模板注册表新增项必须自动进入候选目录。
- topic/copy/script/storyboard/images 必须进入 run 候选区，校验后由用户明确提升。
- V4 发布文案与封面使用独立子状态、独立校验和独立提升；只有两个子产物均已提升且
  hash 未变化时，`publish-finalize` 才能汇总 release。历史 V1–V3 发布包只读。
- 封面模板没有默认选择。Sol 根据正式选题推荐并展示注册表全部选项，用户明确选择后
  才能规划；选择记录绑定 topic hash 且不可变更。正式封面必须使用注册表中用户明确
  选择的版本化模板。`reference_006_v1` 使用必要角色、左侧两行观点钩子与右侧人物；
  `book_spotlight_v2` 的书封与书脊文字由图片生成，右侧文字由本地确定性合成且不得用
  硬边整块遮罩覆盖书籍。
- 发布任务包必须显式记录下一图片阶段的 provider 与 Agent 执行环境。若图片 provider
  为 `imagegen`，Antigravity 写完 copy/cover plan 后必须停止；只有带 Codex 会话标记
  的执行环境才能签发或确认 ImageGen 封面任务，禁止用其他工具产图后冒充 ImageGen。
- 用户笼统要求“执行/测试发布流程”不构成模板、标题、最终封面或提升授权。Agent 每到
  一个对应人工门禁都必须停止并展示候选；只有用户最新回复明确给出 ID 或确认提升后，
  才能执行单个 select/promote，不得一次性代选、代审并 finalize。
- storyboard 必须先校验候选，再运行并校验 storyboard-review；用户确认后执行
  `promote storyboard`，由该操作同时锁定正式分镜与匹配哈希的审核记录。不得先提升
  storyboard 再审核。
- Codex、ImageGen 与 Antigravity 只生成交互任务包；DeepSeek/万相直接写相同候选契约；不得自动回退。
- `script.txt` 是 Azure 与字幕唯一文本源；`storyboard.json` 是图片和渲染唯一分镜源。
- 正式分镜不得出现 provider/model/final prompt/negative prompt 字段。

## Style and QA

Python 遵循 PEP 8，4 空格缩进，中文注释；子进程使用参数数组。测试使用标准库 `unittest`。改动后运行语法检查、单测和与风险相称的 `--frames`/`--pilot` 回归。

## Security

密钥只来自环境变量或根 `.env`，不得写入项目配置、状态或日志。Codex、ImageGen 与 Antigravity 原生任务包不需要项目 API key；调用 DeepSeek、万相或 Azure 前仍需用户授权。候选资产只有在用户明确确认后才可 `promote`。
