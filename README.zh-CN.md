# videoMaker

[English](README.md) | [简体中文](README.zh-CN.md)

面向中文书籍解读的 16:9 长视频生产工作流：选题、文案、口播、分镜与图片，经人工确认后进入 Azure 配音、字幕、运镜、渲染和 QA。发布文案与封面使用各自的选择、校验和确认步骤。

## 工作流

```text
topic → copy → script → storyboard → images
                   └→ voice ─────────┘
                         ↓
                   render → qa
```

每阶段生成候选、校验后由用户明确提升。选题、内容模板、标题和封面模板不能由工具静默代选。分镜必须先完成 `storyboard-review`，再与审核记录一起提升。

## 环境与入口

工作流入口为 `pipeline/workflow.py`。作者环境使用 Codex 捆绑 Python；其他环境需准备兼容的 Python、Pillow，以及渲染阶段所需的 FFmpeg、NumPy 和 jieba。当前没有独立锁定的完整依赖清单。可将 `VIDEO_MAKER_PYTHON` 设置为已准备好的解释器路径。

```bash
PY="${VIDEO_MAKER_PYTHON:-python3}"
"$PY" pipeline/workflow.py --help
"$PY" pipeline/workflow.py create --project 100 --llm codex --image imagegen
# 编辑新项目 input/topic_request.md，再初始化：
"$PY" pipeline/workflow.py init --project 100
```

`100` 只是新项目编号示例，不要对已有项目重建。后续使用初始化返回的 run ID，按 [完整工作流参考](docs/WORKFLOW_GUIDE.md) 逐阶段推进。

## 生成方式与配置

| 环节 | 支持方式 |
| --- | --- |
| 内容 | `codex` 当前会话、`deepseek` API、`antigravity` 当前会话 |
| 图片 | `imagegen` 内置生图、`wanxiang` API、`antigravity` 内置生图 |
| 配音 | Azure Speech，固定服务，不跨服务回退 |

一个项目的生成方式与模型在创建时选定并固定；run 保存快照。原生交互方式不要求项目 API key，但 DeepSeek、万相与 Azure 需要对应授权和配置。Azure 读取 `AZURE_SPEECH_KEY`、`AZURE_REGION`（或区域 URL 配置），音色来自项目配置；密钥仅放环境变量或根目录被忽略的 `.env`。

## 目录与验证

- `pipeline/`：编排、契约、适配器与公共渲染器。
- `projects/`：每本书的输入、候选、工作流状态和发布包。
- `channels/`：频道品牌；`docs/`：详细说明。
- `tests/`：工作流、图片模式和发布契约测试。

```bash
PY="${VIDEO_MAKER_PYTHON:-python3}"
"$PY" -m unittest discover -s tests -v
```

测试不等同于真实配音、生图或整片验收。历史案例反映各自冻结版本；V1–V3 发布包保持只读，当前 V4 分别确认文案与封面后汇总 release。本次文档整理未调用付费服务、提升候选或执行真实发布。

## 许可与素材

当前默认分支未提供项目级许可证文件；公开可见不等于授予复用许可。第三方依赖及素材保留各自条款。

书籍案例、书封、频道研究资料和生成图片不自动附带额外复用授权。随附思源黑体的原有 OFL 声明见 [字体许可](assets/fonts/SourceHanSans-LICENSE.txt)。
