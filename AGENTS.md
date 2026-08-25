# Repository Guidelines

## Model routing

本项目采用 Terra 主控、Sol 设计、Luna 执行的自动路由：

- 默认由 `gpt-5.6-terra` 处理需求沟通、状态检查、普通分析、短小修改、结果汇总与最终验收。
- 遇到架构设计、工作流或数据契约设计、疑难根因分析、多个可行方案的权衡、高风险技术决策、复杂视觉方案时，主代理应自动把边界明确的分析子任务委派给 `sol_architect`；Sol 只读，不直接修改项目。
- 当需求和方案已经冻结，任务属于明确实现、机械修改、执行命令、测试、渲染、格式化、批量检查或重复性迁移时，主代理应自动把执行子任务委派给 `luna_executor`。
- 混合任务先由 Terra 判断复杂度；确需设计时由 Sol 产出冻结方案，再由 Luna 执行，最后由 Terra 校验和交付。不得让两个专用代理重复处理同一任务。
- 小任务、强依赖当前对话上下文的任务，以及委派成本可能高于直接处理的任务保留在 Terra；不得为了形式上的切换而创建代理。
- 同一任务默认最多使用一个专用代理。只有用户明确要求并行，或任务包含彼此独立且足够大的子任务时，才允许增加并行代理。
- 如果指定模型或专用代理不可用，回到 Terra 并明确说明；不得在高风险任务上静默降低模型能力。
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
