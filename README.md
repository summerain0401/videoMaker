# videoMaker

面向中文书籍解读的 16:9 长视频生产流水线。当前架构把模型能力隔离在适配器中，正式资产和渲染器不依赖任何特定 LLM 或生图模型。

## 架构

```text
LLM provider                    Image provider
topic → copy → script → storyboard → ImageTask → images
   │       每阶段候选、校验、人工提升          │
   └──────────────────┬───────────────────────┘
                      ↓
        Azure voice + 字幕/SFX/BGM/运镜/渲染/QA
```

- LLM：默认 `codex`，可切换 `deepseek`。
- 图片：默认 `imagegen`，可切换 `wanxiang`。
- 语音：固定 Azure，不存在 Piper、Edge 或系统语音回退。
- provider 只在项目级配置；单个 run 完整快照，禁止阶段覆盖和跨模型自动回退。

## 快速开始

一律使用仓库约定的捆绑 Python：

```bash
PY=/Users/spring/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

$PY pipeline/workflow.py create --project 003 --llm codex --image imagegen \
  --content-template story_journey_v1
# 编辑 projects/003_新项目/input/topic_request.md
$PY pipeline/workflow.py init --project 003
$PY pipeline/workflow.py run <run_id> topic
$PY pipeline/workflow.py select-topic <run_id> <candidate_id>
$PY pipeline/workflow.py verify <run_id> topic
$PY pipeline/workflow.py promote <run_id> topic
```

随后依次处理 `copy`、`script`、`storyboard`、`images`。每个阶段都必须先 `verify`，再由人明确执行 `promote`。`script` 提升后 `voice` 可运行，`storyboard` 提升后 `images` 可运行，两条分支可以并行；图片与语音都完成后运行 `render` 和 `qa`：

```bash
$PY pipeline/workflow.py run <run_id> voice
$PY pipeline/workflow.py run <run_id> images
# 新项目首次仅生成一张首图候选；人工确认其风格后固定为本 run 锚点。
$PY pipeline/workflow.py select-image-anchor <run_id> <首图_key>
$PY pipeline/workflow.py run <run_id> images
$PY pipeline/workflow.py run <run_id> render
$PY pipeline/workflow.py run <run_id> qa
$PY pipeline/workflow.py status <run_id>
```

Codex 和 ImageGen 是交互式适配器：`run` 写任务包并进入 `awaiting_external`，由 `$video-maker-production` 读取任务包并写候选文件。DeepSeek 和万相直接调用 API，但候选路径和正式契约完全相同。

首次图片没有既有视觉锚点时，工作流只生成一张首图候选；执行
`select-image-anchor` 后会把其路径和 SHA-256 冻结在 run 状态中，第二次
`run images` 才生成余下图片。正常图片审核仍需 `run image-review`、人工写入
审核结果、`verify image-review` 后提升。仅对已经完成逐张人工审核的历史候选，
可使用 `image-review-exception <run_id> --reason "..."` 写入哈希绑定的例外记录；
它只豁免首批锚点时序，不会绕过任务包、候选图片、比例或重复性校验，也不会自动提升。

## 正式契约

项目的 `input/` 只保留四阶段正式资产：

- `topic.json`：书、作者、切入角度、受众承诺、标题、理由。
- `copy.json`：核心论点、事实声明、五段结构、案例、行动建议。
- `script.txt`：严格口播格式；Azure 和字幕的唯一文本源。
- `storyboard.json`：块/拍、句子覆盖、语义画面、角色、景别、情绪、`segment`；不含 provider、模型 Prompt 或 negative prompt。

`project.json.providers` 是唯一提供商配置源。API 密钥只从环境变量或根目录 `.env` 读取。

## 内容模板

项目创建时可通过 `--content-template` 选择讲述结构；该选择会写入
`project.json`，并在 `init` 时连同版本与哈希快照进每个 run。已有项目未配置时
默认采用 `classic_insight_v1`。当前内置模板为：

- `classic_insight_v1`：共情、病灶、模型、工具、升华。
- `story_journey_v1`：人物处境、冲突升级、关键发现、转折、落地启示。
- `practical_workshop_v1`：问题诊断、核心原则、操作步骤、案例演练、行动清单。

## 验证

```bash
$PY -m py_compile pipeline/*.py pipeline/providers/*.py
$PY -m unittest discover -s tests -v
$PY pipeline/build_long.py --project 001 --frames
```

001/002 的旧分镜已迁移到 `archive/pre_provider_refactor/`，迁移清单记录了剧本哈希、块数、拍数和历史图片键。

完整操作流程见 [docs/长视频工作流.md](docs/长视频工作流.md)。
# videoMaker

视频制作完成后，可通过独立的品牌与发布准备流程生成平台适配文案。该流程不修改内容阶段、图片、配音或成片，也不会自动上传。

```bash
python3 pipeline/workflow.py brand-init --project 001 --channel main
python3 pipeline/workflow.py brand-run <brand_run_id> --project 001 --channel main
python3 pipeline/workflow.py brand-select <brand_run_id> --project 001 --channel main --name-id name_0 --visual-id visual_0
python3 pipeline/workflow.py brand-verify <brand_run_id> --project 001 --channel main
python3 pipeline/workflow.py brand-promote <brand_run_id> --project 001 --channel main
python3 pipeline/workflow.py publish-init <video_run_id> --project 001 --channel main
python3 pipeline/workflow.py publish-run <video_run_id> <publish_id> --project 001 --channel main --revision v2
python3 pipeline/workflow.py publish-verify <video_run_id> <publish_id> --project 001 --channel main --revision v2
python3 pipeline/workflow.py publish-promote <video_run_id> <publish_id> --project 001 --channel main --revision v2
```

发布任务会从项目 `assets/scenes/` 中按文件名选择最多三张正式常规 PNG 作为封面风格与角色参考（排除 `phase_*.png` 和候选素材）。封面任务包会锁定这些文件的路径与 SHA-256；生成封面时必须将其作为 input references，并保持与正式成片一致的画风、角色、比例、线条、色彩和光影。

品牌和发布候选均须人工选择/确认后提升；`promote` 只生成发布清单，不执行平台上传。
