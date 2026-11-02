# videoMaker

[中文](README.md) | [English](README.en.md)

A 16:9 long-form video workflow for Chinese book commentary. Topics, copy, narration scripts, storyboards, and images pass human review before Azure speech, subtitles, motion, rendering, and QA. Publishing copy and covers have separate selection, verification, and approval steps.

## Workflow

```text
topic → copy → script → storyboard → images
                   └→ voice ─────────┘
                         ↓
                   render → qa
```

Each stage produces candidates that are verified and explicitly promoted by the user. Topic, content template, title, and cover template selection are human decisions. Storyboards must pass `storyboard-review` before being promoted together with the matching review record.

## Environment and entry point

Use `pipeline/workflow.py`. The author's setup uses Codex's bundled Python. Other environments need compatible Python, Pillow, and FFmpeg, NumPy, and jieba for rendering. There is no standalone locked dependency manifest yet. Point `VIDEO_MAKER_PYTHON` to a prepared interpreter if needed.

```bash
PY="${VIDEO_MAKER_PYTHON:-python3}"
"$PY" pipeline/workflow.py --help
"$PY" pipeline/workflow.py create --project 100 --llm codex --image imagegen
# Edit the new project's input/topic_request.md, then initialize:
"$PY" pipeline/workflow.py init --project 100
```

`100` is an example new project ID; do not recreate existing projects. Use the run ID returned by initialization and follow the [complete workflow reference](docs/WORKFLOW_GUIDE.md) stage by stage. That reference remains in Chinese.

## Generation methods and configuration

| Stage | Methods |
| --- | --- |
| Content | `codex` session, `deepseek` API, `antigravity` session |
| Images | `imagegen` built-in generation, `wanxiang` API, `antigravity` generation |
| Speech | Azure Speech only; no cross-service fallback |

Generation methods and models are selected at project creation and remain fixed. Runs store a snapshot. Native interactive methods do not require project API keys; DeepSeek, Wanxiang, and Azure require their own authorization/configuration. Azure reads `AZURE_SPEECH_KEY` and `AZURE_REGION` (or a region URL); the voice comes from project configuration. Keep credentials in environment variables or the ignored root `.env` only.

## Structure and checks

- `pipeline/`: orchestration, contracts, adapters, and shared rendering.
- `projects/`: book inputs, candidates, workflow state, and publishing packages.
- `channels/`: channel branding; `docs/`: detailed instructions.
- `tests/`: workflow, image-mode, and publishing-contract tests.

```bash
PY="${VIDEO_MAKER_PYTHON:-python3}"
"$PY" -m unittest discover -s tests -v
```

Tests do not establish successful live speech, image generation, or a complete film review. Historical examples represent frozen versions. V1–V3 publishing packages remain read-only; V4 requires separate copy and cover approvals before release aggregation. No paid service, candidate promotion, or real publication was executed for this documentation update.

## License and assets

The default branch does not include a project-level license file. Public visibility does not itself grant reuse rights. Third-party dependencies and assets retain their own terms.

Book examples, covers, channel research, and generated images do not automatically carry additional reuse permission. The bundled Source Han Sans font's existing OFL terms are retained in the [font license](assets/fonts/SourceHanSans-LICENSE.txt).
