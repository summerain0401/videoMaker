# Repository Guidelines

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
