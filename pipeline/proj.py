#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目制路径解析：按 PROJECT（默认 001）定位 projects/{id}_* 项目目录。

长视频生产按项目组织，每个项目一个目录（数字前缀 + 中文名，如
`001_金钱的艺术`），内部按「输入 / 中间产物 / 产出」分层：

  projects/{id}_书名/
    input/      文案与分镜（brief.md、script.txt、storyboard_narrative.json…）
    assets/     卡点画面（scenes/）、历史底图（art/）、渲染中间层（layers/）
    audio/      配音缓存（voice/）、背景乐、合成中间（tmp/）
    output/     成片（long_{id}*.mp4）、分块（vs2_*）、抽帧（preview/）、报告

规则：
  - 项目 id 来自环境变量 PROJECT（默认 "001"），各脚本的 --project 参数
    可覆盖（调用方先设置 CURRENT_ID 再取路径）。
  - 目录按 projects/{id}_* 前缀匹配：唯一命中即用；零命中自动创建
    projects/{id}_新项目（含子目录与 project.json）并提示可改名；
    多命中视为配置错误，列出候选后退出。
  - project.json 为静态元数据（id/title/author/status），仅在目录首次创建
    时写入，运行期间不自动改写，避免弄脏工作区。
"""

import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_DIR = os.path.join(ROOT, "projects")
DEFAULT_ID = "001"
CURRENT_ID = os.environ.get("PROJECT") or DEFAULT_ID
_CACHE = {}

SUBDIRS = ("input", "assets/scenes", "assets/art", "assets/layers",
           "audio/voice", "audio/tmp", "output")


def P(*parts):
    """仓库根路径（共享代码/文档/运行时依赖）。"""
    return os.path.join(ROOT, *parts)


def _find_dir(pid):
    """按前缀匹配项目目录名；无匹配返回 None。"""
    if not os.path.isdir(PROJECTS_DIR):
        return None
    candidates = []
    for name in sorted(os.listdir(PROJECTS_DIR)):
        if name.startswith(pid + "_") and \
                os.path.isdir(os.path.join(PROJECTS_DIR, name)):
            candidates.append(name)
    if len(candidates) > 1:
        print(f"PROJECT={pid} 匹配到多个项目目录，请指定唯一 id：")
        for c in candidates:
            print("  -", c)
        raise SystemExit(2)
    if len(candidates) == 1:
        return candidates[0]
    if os.path.isdir(os.path.join(PROJECTS_DIR, pid)):
        return pid
    return None


def _write_project_json(proj_dir, pid, title, author):
    """首次创建时写入元数据；已存在则不覆盖。"""
    path = os.path.join(proj_dir, "project.json")
    if os.path.exists(path):
        return
    meta = {
        "id": pid,
        "title": title,
        "author": author,
        "status": "进行中",
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def project_dir(pid=None, title="", author=""):
    """返回项目目录绝对路径（结果缓存）；目录缺失时自动创建。"""
    pid = pid or CURRENT_ID
    if pid in _CACHE:
        return _CACHE[pid]
    name = _find_dir(pid)
    created = name is None
    if created:
        name = f"{pid}_新项目"
    proj_dir = os.path.join(PROJECTS_DIR, name)
    os.makedirs(proj_dir, exist_ok=True)
    for sub in SUBDIRS:
        os.makedirs(os.path.join(proj_dir, sub), exist_ok=True)
    _write_project_json(proj_dir, pid, title, author)
    _CACHE[pid] = proj_dir
    if created:
        print(f"提示：未找到 PROJECT={pid} 项目，已自动创建 {proj_dir}，"
              f"可重命名为 projects/{pid}_书名。")
    return proj_dir


def PROJ(*parts):
    """项目内路径（输入/中间产物/产出均按当前项目解析）。"""
    return os.path.join(project_dir(), *parts)


def read_meta(pid=None):
    """读取项目 project.json（含 visual_style 等元数据）；不存在返回空 dict。"""
    d = project_dir(pid)
    path = os.path.join(d, "project.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
