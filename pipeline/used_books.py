"""跨项目已用书目索引，正式选题是唯一数据来源。"""

import json
import os
import re
import unicodedata


def _normalize(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in text if char.isalnum())


def _main_title(value):
    return re.split(r"[：:]", str(value or ""), maxsplit=1)[0]


def collect_used_books(projects_dir):
    """收集正式选题及被替换前的正式选题；同项目同书只列一次。"""
    entries = []
    if not os.path.isdir(projects_dir):
        return entries
    for dirname in sorted(os.listdir(projects_dir)):
        project = os.path.join(projects_dir, dirname)
        if not os.path.isdir(project) or "_" not in dirname:
            continue
        project_id = dirname.split("_", 1)[0]
        input_dir = os.path.join(project, "input")
        if not os.path.isdir(input_dir):
            continue
        files = ["topic.json"] + sorted(
            name for name in os.listdir(input_dir)
            if name.startswith("topic.json.bak."))
        seen = set()
        for filename in files:
            path = os.path.join(input_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                topic = json.load(handle)
            title = str(topic.get("book_title") or "").strip()
            author = str(topic.get("author") or "").strip()
            if not title:
                continue
            identity = (_normalize(title), _normalize(author))
            if identity in seen:
                continue
            seen.add(identity)
            entries.append({
                "project_id": project_id,
                "book_title": title,
                "author": author,
                "source": "正式选题" if filename == "topic.json" else "历史选题",
            })
    return entries


def duplicate_book_problems(candidates, used_books, current_project_id):
    """同名书或同作者的主标题相同视为重复。"""
    problems = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        title = candidate.get("book_title")
        author = candidate.get("author")
        if not _normalize(title):
            continue
        for used in used_books:
            if used["project_id"] == str(current_project_id):
                continue
            same_author = (_normalize(author) and
                           _normalize(author) == _normalize(used["author"]))
            same_title = (same_author and
                          _normalize(title) == _normalize(used["book_title"]))
            same_main = (_normalize(_main_title(title)) ==
                         _normalize(_main_title(used["book_title"])) and
                         same_author)
            if same_title or same_main:
                problems.append(
                    f"候选 {candidate.get('id', '?')} 书目已用于项目 "
                    f"{used['project_id']}：《{used['book_title']}》")
                break
    return problems


def refresh_used_books_catalog(projects_dir):
    """从正式选题重建供人工查阅的清单。"""
    entries = collect_used_books(projects_dir)
    destination = os.path.join(os.path.dirname(projects_dir),
                               "docs", "used_books.md")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    lines = [
        "# 已做书单",
        "",
        "由各项目的正式 `input/topic.json` 自动汇总；替换过的正式选题也会保留。",
        "新选题任务包会附上此书单，重复书目会在 topic 校验与提升时被拦截。",
        "",
        "| 项目 | 书名 | 作者 | 记录 |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        values = [entry[key].replace("|", "\\|") for key in (
            "project_id", "book_title", "author", "source")]
        lines.append("| " + " | ".join(values) + " |")
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return destination
