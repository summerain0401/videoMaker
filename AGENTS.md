# Repository Guidelines

## Project Structure & Module Organization

- `pipeline/` — 共享构建脚本：`proj.py`（项目制路径解析）、`codex_jobs.py`（Codex 原生任务状态/候选资产/提升）、`build_long.py`（16:9 长视频 V5 主引擎）、`long_visuals.py`（画面元素库）、`tts_piper.py`（本地神经 TTS）、`tts_edge.py`（微软 Edge 在线 TTS，免费无密钥）、`tts_azure.py`（Azure 正式语音，需密钥）、`write_long_copy.py`（DeepSeek API 后备文案起草）、`write_storyboard.py`（DeepSeek API 后备叙事分镜）、`write_image_art.py`（万相 API 后备生图）。
- `projects/{id}_书名/` — 单个长视频项目：`input/`（brief、script、叙事/输出分镜、候选资产）、`assets/`（scenes/ 卡点画面、art/ 历史底图、layers/ 渲染中间层）、`audio/`（voice/ 配音缓存、背景乐、tmp/）、`output/`（成片、vs2_* 分块、preview/ 抽帧、报告与 Codex run 状态）。
- `assets/piper/` — 共享 Piper 模型（运行时依赖，不入库）。
- `docs/` — 工作流文档（`docs/长视频工作流.md`）。
- 文档：`PROJECT_PLAN.md`（规划）、`HANDOFF.md`（交接）、`report.pdf`（频道分析）。

项目定位规则：所有脚本按 `PROJECT` 环境变量（默认 `001`）或 `--project`
参数解析项目目录（见 `pipeline/proj.py`）；根目录不存放任何项目数据。

## Build, Test, and Development Commands

```bash
# 项目切换：PROJECT=002 … 或 --project 002（默认 001_金钱的艺术）

# 默认：Codex 中使用 $video-maker-production；此命令只创建本地可恢复 run，不调用 API
python3 pipeline/codex_jobs.py init

# 长视频全片 / 样段（必须提权运行：Piper 的 PyTorch 共享内存被沙盒限制）
python3 pipeline/build_long.py
python3 pipeline/build_long.py --pilot

# 长视频文案 AI 起草（DeepSeek 五段式完整脚本，密钥自动读项目根 .env）
python3 pipeline/write_long_copy.py --provider deepseek
python3 pipeline/write_long_copy.py --check projects/001_金钱的艺术/input/script.txt   # 离线校验
python3 pipeline/write_long_copy.py --accept                        # 人工审阅后定稿

# 长视频 AI 插画（通义万相 wan2.7-image，密钥自动读 .env）
python3 pipeline/write_image_art.py
python3 pipeline/write_image_art.py --force --only COVER   # 封面图

# 叙事分镜 + 卡点画面（画面讲卡点模式）
python3 pipeline/write_storyboard.py
python3 pipeline/write_storyboard.py --refine   # 单拍>12s 的拍自动拆半（AI 补提示词）
python3 pipeline/write_image_art.py --story
python3 pipeline/build_long.py --frames   # 抽帧验收：文字卡 m3_*.jpg / 叙事 m3n_*.jpg

# 视觉样片（跳过 TTS、只渲染指定块）
python3 pipeline/build_long.py --blocks 0,1,2,3,4,7,8,9,12,13 --no-tts

# 视觉样片（微软 edge-tts，免费无需密钥；依赖 edge-tts 库）
TTS_SOURCE=edge python3 pipeline/build_long.py --blocks 0,1,2   # 默认男声 YunyangNeural

# Azure 正式语音（.env 配 AZURE_SPEECH_KEY/AZURE_REGION/AZURE_VOICE）
TTS_SOURCE=azure python3 pipeline/build_long.py --blocks 0,1

# 语法自检
python3 -m py_compile pipeline/*.py
```

一律使用捆绑 Python：`/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。

## Coding Style & Naming Conventions

- Python 遵循 PEP 8，4 空格缩进，函数/变量用 `snake_case`，中文注释与文档字符串。
- 文件名用 ASCII；对外文件（文案/成片/项目目录中文名）可用中文。
- 子进程调用传参数列表（不用 shell 拼接），避免转义与注入。
- 环境变量大写（`PROJECT`、`TTS_SOURCE`、`PIPER_LENGTH_SCALE`）；缓存文件名携带配置（如 `blk00_azurezh-CN-Xiaochen:DragonHDFlashLatestNeural_<哈希>.wav`）。

## Testing Guidelines

无单元测试框架；以端到端质检代替：`ffprobe` 校验时长/分辨率、`volumedetect` 校验响度（目标 -14 LUFS）、抽帧检查元素、相邻帧差验证运镜、完整解码零错误。改动后先跑 `--pilot` 再全片。

## Commit & Pull Request Guidelines

采用 Conventional Commits：`feat:` / `fix:` / `refactor:` / `docs:` / `perf:`，正文说明改动与影响。PR 需描述改动、附 QA 结果与关键帧/成片链接；涉及缓存或音色变更时注明需清理的产物。

## Security & Configuration Tips

- API 密钥只走环境变量（`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 等）或项目根 `.env`（已被 `.gitignore` 排除），绝不写入仓库或提交。
- `.env`、项目 `audio/voice/`、`audio/tmp/`、`assets/layers/`、成片 mp4、preview 均由 `.gitignore` 排除；提交前检查 `git status` 确认无混入。
- 默认 Codex 制作使用内置文本与 ImageGen，不配置 `OPENAI_API_KEY`，不调用 API；候选资产仅在用户明确确认后执行 `codex_jobs.py promote`。DeepSeek / 万相 / Azure 等外部服务调用前仍需用户授权；`piper`/`say` 必须提权运行。
- 模型与拼音数据已本地化（`assets/piper/`），首次安装依赖需联网授权一次。
