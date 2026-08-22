# 项目交接

## 架构状态

- 唯一编排入口：`pipeline/workflow.py`。
- 正式契约：`input/topic.json`、`copy.json`、`script.txt`、`storyboard.json`。
- LLM registry：Codex（交互式，默认）/ DeepSeek（API）。
- 图片 registry：ImageGen（交互式，默认）/ 万相（API）。
- TTS：仅 Azure；音色来自 `project.json`，凭据来自环境变量或 `.env`。
- 公共层：字幕、Ken Burns 运镜、SFX、三段 BGM、1080p 渲染和 ffprobe/完整解码 QA。

## 迁移状态

001 与 002 已迁移。旧 `storyboard_narrative.json` / `storyboard_output.json` 位于各项目 `archive/pre_provider_refactor/`；`migration_manifest.json` 记录迁移前后剧本哈希、块数、拍数和历史图片键。新引擎只读取 `storyboard.json`。

## 工作约束

- 活动 run 期间不能修改 provider。
- Codex/ImageGen 的 `run` 只写任务包并等待 `$video-maker-production` 写候选。
- 所有模型候选必须 `verify`，并在用户明确确认后 `promote`。
- DeepSeek、万相和 Azure 失败时保留 run 以便原 provider 重试；绝不跨 provider 回退。
- script 提升后 voice/storyboard 可并行；render 等待 voice/images。

## 交接检查

```bash
PY=/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PY -m py_compile pipeline/*.py pipeline/providers/*.py
$PY -m unittest discover -s tests -v
$PY pipeline/workflow.py --help
$PY pipeline/build_long.py --project 001 --frames
```

被移除的旧入口包括 Codex 专属状态机、两套分镜生成器、旧万相脚本、Piper、Edge 和系统 TTS 分支；不要恢复第二套状态或文件格式。
