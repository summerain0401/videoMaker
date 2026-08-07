# Repository Guidelines

## Project Structure & Module Organization

- `pipeline/` — Python 构建脚本：`build.py`（9:16 短视频）、`build_long.py`（16:9 长视频 V2 主引擎）、`long_visuals.py`（画面元素库）、`tts_piper.py`（本地神经 TTS）、`write_copy.py`（短视频文案起草）、`write_long_copy.py`（长视频文案起草）、`write_storyboard.py`（叙事分镜）、`write_image_art.py`（通义万相插画生成）。
- `copy/` — 文案源：`voiceover.txt`（短视频）、`long/script.txt`（长视频，唯一文案源）、`brief.md`（需求单）、草稿 `draft_*.txt`。
- `assets/` — 素材与中间层：`piper/`（模型）、`long/`（Pillow 生成的图层）、`ai/`（AI 插画位）、`txt/`。
- `audio/` — 配音与音乐（`long/` 含可复用缓存，命名带配置后缀）。
- `output/`、`script/` — 成片/预览帧、自动生成的分镜 CSV。
- 文档：`PROJECT_PLAN.md`（规划）、`HANDOFF.md`（交接）、`report.pdf`（频道分析）。

## Build, Test, and Development Commands

```bash
# 长视频全片 / 样段（必须提权运行：Piper 的 PyTorch 共享内存被沙盒限制）
python3 pipeline/build_long.py
python3 pipeline/build_long.py --pilot

# 短视频
python3 pipeline/build.py

# AI 起草文案（DeepSeek/Kimi，人工定稿后 --accept）
python3 pipeline/write_copy.py --provider deepseek

# 长视频文案 AI 起草（DeepSeek 五段式完整脚本，密钥自动读项目根 .env）
python3 pipeline/write_long_copy.py --provider deepseek
python3 pipeline/write_long_copy.py --check copy/long/script.txt   # 离线校验
python3 pipeline/write_long_copy.py --accept                        # 人工审阅后定稿

# 长视频 AI 插画底图（通义万相 wan2.7-image-pro，密钥自动读 .env）
python3 pipeline/write_image_art.py

# 叙事分镜 + 卡点画面（画面讲卡点模式）
python3 pipeline/write_storyboard.py
python3 pipeline/write_image_art.py --story
python3 pipeline/build_long.py --frames   # 抽帧验收：文字卡 m3_*.jpg / 叙事 m3n_*.jpg

# 语法自检
python3 -m py_compile pipeline/*.py
```

一律使用捆绑 Python：`/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。

## Coding Style & Naming Conventions

- Python 遵循 PEP 8，4 空格缩进，函数/变量用 `snake_case`，中文注释与文档字符串。
- 文件名用 ASCII；对外文件（文案/成片）可用中文。
- 子进程调用传参数列表（不用 shell 拼接），避免转义与注入。
- 环境变量大写（`TTS_SOURCE`、`PIPER_LENGTH_SCALE`）；缓存文件名携带配置（如 `blk00_piperls1.15.wav`）。

## Testing Guidelines

无单元测试框架；以端到端质检代替：`ffprobe` 校验时长/分辨率、`volumedetect` 校验响度（目标 -14 LUFS）、抽帧检查元素、相邻帧差验证运镜、完整解码零错误。改动后先跑 `--pilot` 再全片。

## Commit & Pull Request Guidelines

仓库暂无提交历史，建议采用 Conventional Commits：`feat:` / `fix:` / `docs:` / `perf:`，正文说明改动与影响。PR 需描述改动、附 QA 结果与关键帧/成片链接；涉及缓存或音色变更时注明需清理的产物。

## Security & Configuration Tips

- API 密钥只走环境变量（`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 等）或项目根 `.env`（已被 `.gitignore` 排除），绝不写入仓库或提交。
- 外部服务调用前需用户授权；`piper`/`say` 必须提权运行。
- 模型与拼音数据已本地化（`assets/piper/`），首次安装依赖需联网授权一次。
