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

$PY pipeline/workflow.py create --project 003 --llm codex --image imagegen
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
$PY pipeline/workflow.py run <run_id> render
$PY pipeline/workflow.py run <run_id> qa
$PY pipeline/workflow.py status <run_id>
```

Codex 和 ImageGen 是交互式适配器：`run` 写任务包并进入 `awaiting_external`，由 `$video-maker-production` 读取任务包并写候选文件。DeepSeek 和万相直接调用 API，但候选路径和正式契约完全相同。

## 正式契约

项目的 `input/` 只保留四阶段正式资产：

- `topic.json`：书、作者、切入角度、受众承诺、标题、理由。
- `copy.json`：核心论点、事实声明、五段结构、案例、行动建议。
- `script.txt`：严格口播格式；Azure 和字幕的唯一文本源。
- `storyboard.json`：块/拍、句子覆盖、语义画面、角色、景别、情绪、`segment`；不含 provider、模型 Prompt 或 negative prompt。

`project.json.providers` 是唯一提供商配置源。API 密钥只从环境变量或根目录 `.env` 读取。

## 验证

```bash
$PY -m py_compile pipeline/*.py pipeline/providers/*.py
$PY -m unittest discover -s tests -v
$PY pipeline/build_long.py --project 001 --frames
```

001/002 的旧分镜已迁移到 `archive/pre_provider_refactor/`，迁移清单记录了剧本哈希、块数、拍数和历史图片键。

完整操作流程见 [docs/长视频工作流.md](docs/长视频工作流.md)。
