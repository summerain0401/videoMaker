# Repository Guidelines

## Model routing

本项目仅使用 Sol 和 Luna：Sol 主控、创作与工程判断，Luna 按需执行明确任务。

- 默认主控为 `gpt-5.6-sol`，推理强度为 `medium`；负责需求沟通、任务包、内容创作、架构设计、工程实现、复杂调试、调度与最终验收。仅在任务确有需要且运行环境支持时提高推理强度，不默认使用高强度推理；不得声称配置文件修改已热切换当前会话模型。
- `topic`、`copy`、`script`、`storyboard` 的新候选与任何主题、论点、叙事、案例、口播或镜头语义的实质修订均由 Sol 主控直接完成，不再为这些阶段例行启动另一个 Sol 子代理。`script` 仍是独立创作，不得作为 `copy` 的机械转写。
- Sol 读取正式输入、任务包与契约后，产出满足 `output_contract` 的完整候选或冻结修订稿。Sol 主控可写文件、运行命令和执行验证；这些操作不受可选只读咨询角色的限制。
- `luna_executor` 使用 `gpt-5.6-luna` / `low`，仅接收输入、修改范围、预期结果和验证方法均明确的任务。适合批量落盘、格式化、语法检查、`verify`、单测、渲染、重复检查以及方案确定的小改，不得自行补充需求或重新设计。
- 内容委派采用“Sol 创作与冻结 → Luna 原样落盘与验证 → Sol 验收”。Luna 只能修复不改变语义的格式问题；语义、叙事、画面或质量问题退回 Sol。工程接口、状态、契约或跨模块问题也交给 Sol 判断，不得为通过测试而放宽标准。
- 小任务、短候选落盘、单次命令及强依赖当前上下文的工作由 Sol 直接完成。只有执行量足以抵消交接成本时才调用 Luna，不为每个阶段强制增加代理轮次。
- 委派只传必要输入、路径、冻结结果和验收要求，避免复制整段对话、重复创作或重复校验；执行代理返回简短摘要、验证结果与阻塞，不回传无关完整日志。同一时刻最多一个专用子代理，子代理不得继续委派。
- `sol_architect` 保留为 `gpt-5.6-sol` / `high` 的可选只读独立复核角色，仅在用户明确要求独立复核时使用；普通创作、架构与调试均由 Sol 主控直接处理。
- 不调用 Astra、Terra 或其他主控/执行模型，也不自动升级到它们。Sol 不可用时暂停需要创作或判断的工作并说明；Luna 不可用时由 Sol 执行必要机械步骤。
- `select-topic` 由用户选择后执行，候选资产仍须用户明确确认后方可 `promote`；模型分工不改变人工选择与提升边界。
- 上述模型分工属于 Codex 内部代理路由，不改变项目的单一 LLM provider 与单一图片 provider 配置，也不得增加阶段 provider 覆盖。
- 无论由哪个模型执行，破坏性操作、外部发布、密钥使用和候选资产提升仍遵循本文件的授权与安全规则。

## Structure

- `pipeline/workflow.py`：唯一 provider-neutral 编排入口。
- `pipeline/workflow_contracts.py`：四阶段 schema、校验、ImageTask 组装。
- `pipeline/providers/`：LLM registry（Codex/DeepSeek）与图片 registry（ImageGen/万相）。
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

- 每次开始新视频项目时，先确认用户选择 ImageGen（`imagegen`）还是万相 API（`wanxiang`）；用户已明确指定时直接采用。通过 `create --image` 将选择写入该新项目，不修改全局默认或其他项目。
- 一个项目只能配置一个 LLM 和一个图片 provider；图片 provider 及模型在创建时选定后项目内固定，完成后也不切换；需要另一种生图模式时新建项目。不得增加阶段覆盖参数或修改已有 run 快照。
- `state.json` 必须保存 `project.json.providers` 的完整快照。
- topic/copy/script/storyboard/images 必须进入 run 候选区，校验后由用户明确提升。
- Codex/ImageGen 只生成任务包；DeepSeek/万相只写相同候选契约；不得自动回退。
- `script.txt` 是 Azure 与字幕唯一文本源；`storyboard.json` 是图片和渲染唯一分镜源。
- 正式分镜不得出现 provider/model/final prompt/negative prompt 字段。

## Style and QA

Python 遵循 PEP 8，4 空格缩进，中文注释；子进程使用参数数组。测试使用标准库 `unittest`。改动后运行语法检查、单测和与风险相称的 `--frames`/`--pilot` 回归。

## Security

密钥只来自环境变量或根 `.env`，不得写入项目配置、状态或日志。默认 Codex/ImageGen 不需要 `OPENAI_API_KEY`。调用 DeepSeek、万相或 Azure 前仍需用户授权。候选资产只有在用户明确确认后才可 `promote`。
