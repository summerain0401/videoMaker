# Repository Guidelines

## Model routing

本项目采用 Terra 主控、Sol 创作与设计、Luna 执行的自动路由：

- 默认由 `gpt-5.6-terra` 处理需求沟通、任务包生成与核对、状态检查、普通分析、短小修改、调度、结果汇总与最终验收。
- `topic`、`copy`、`script`、`storyboard` 四个内容阶段的新候选生成，以及任何改变主题、论点、叙事、案例、口播表达或镜头语义的实质修订，不论任务大小，必须由 `gpt-5.6-sol` 完成。`topic` 包括候选角度、标题、受众承诺和理由的创作，不包括用户选择；`script` 属于独立的创造性工作，不得视为 `copy` 的机械转写。
- 上述四个内容阶段由 `sol_architect` 只读正式输入、任务包、契约及待修候选，并产出满足 `output_contract` 的完整候选内容或冻结修订稿。Sol 不直接写入工作区，不运行命令，不改变 state，不执行 `verify` 或 `promote`；这里“产出候选”仅指内容产出，不指文件落盘。
- `luna_executor` 只负责将 Sol 的冻结结果原样写入任务包指定的 `candidate_path`，并执行格式化、语法检查、`verify`、测试、渲染、批量检查和其他机械步骤；只允许修复不改变语义的 JSON 或文本格式问题。校验失败若涉及内容、叙事、画面语义或质量，必须退回 Sol 修订，Luna 与 Terra 不得代写。
- Terra 负责收集需求、归类用户反馈、生成和核对任务包、调度 Sol 与 Luna、汇总结果并最终验收；Terra 不得直接生成或实质改写上述四阶段候选。`select-topic` 仍由用户选择后执行，候选资产仍须用户明确确认后方可 `promote`。
- 遇到架构设计、工作流或数据契约设计、疑难根因分析、多个可行方案的权衡、高风险技术决策、复杂视觉方案时，主代理也应自动把边界明确的分析子任务委派给 `sol_architect`；Sol 保持只读。
- 混合任务先由 Terra 判断复杂度；需要创作或设计时由 Sol 产出冻结结果，再由 Luna 执行，最后由 Terra 校验和交付。不得让两个专用代理重复处理同一职责。
- 小任务、强依赖当前对话上下文的非创作任务，以及委派成本可能高于直接处理的非创作任务可保留在 Terra；此规则不得覆盖四个内容阶段的强制 Sol 路由。
- 同一任务默认最多使用一个专用代理。四个内容阶段允许按“Sol 创作 → Luna 落盘与验证 → Terra 验收”串行使用两个专用代理，因职责不同不视为重复处理；其他任务只有在用户明确要求并行，或包含彼此独立且足够大的子任务时，才允许增加并行代理。
- 四个内容阶段若 Sol 不可用，必须暂停当前内容阶段并明确告知用户，不得回退到 Terra 或 Luna 代写。其他任务若指定模型或专用代理不可用，可回到 Terra 并明确说明；不得在高风险任务上静默降低模型能力。
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

- 一个项目只能配置一个 LLM 和一个图片 provider；不得增加阶段覆盖参数。
- `state.json` 必须保存 `project.json.providers` 的完整快照。
- topic/copy/script/storyboard/images 必须进入 run 候选区，校验后由用户明确提升。
- Codex/ImageGen 只生成任务包；DeepSeek/万相只写相同候选契约；不得自动回退。
- `script.txt` 是 Azure 与字幕唯一文本源；`storyboard.json` 是图片和渲染唯一分镜源。
- 正式分镜不得出现 provider/model/final prompt/negative prompt 字段。

## Style and QA

Python 遵循 PEP 8，4 空格缩进，中文注释；子进程使用参数数组。测试使用标准库 `unittest`。改动后运行语法检查、单测和与风险相称的 `--frames`/`--pilot` 回归。

## Security

密钥只来自环境变量或根 `.env`，不得写入项目配置、状态或日志。默认 Codex/ImageGen 不需要 `OPENAI_API_KEY`。调用 DeepSeek、万相或 Azure 前仍需用户授权。候选资产只有在用户明确确认后才可 `promote`。
