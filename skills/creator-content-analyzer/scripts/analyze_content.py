#!/usr/bin/env python3
"""校验 Creator Content Corpus 并生成证据化统计摘要。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


VALID_TYPES = {"answer", "article", "pin", "other"}


def is_http_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_corpus(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["顶层必须是 JSON 对象"]
    required = {"schema_version", "meta", "author", "items", "errors"}
    missing = sorted(required - set(data))
    if missing:
        errors.append(f"缺少顶层字段: {', '.join(missing)}")
    if data.get("schema_version") != "1.0.0":
        errors.append("schema_version 必须是 1.0.0")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta 必须是对象")
        meta = {}
    for key in ("platform", "source_profile_url", "captured_at", "collection_method", "requested_types", "coverage"):
        if key not in meta:
            errors.append(f"meta 缺少字段: {key}")
    if meta.get("source_profile_url") is not None and not is_http_url(meta.get("source_profile_url")):
        errors.append("meta.source_profile_url 不是有效 HTTP(S) URL")
    coverage = meta.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("meta.coverage 必须是对象")
        coverage = {}
    for key in ("discovered", "collected", "failed", "complete", "note"):
        if key not in coverage:
            errors.append(f"meta.coverage 缺少字段: {key}")

    items = data.get("items")
    if not isinstance(items, list):
        errors.append("items 必须是数组")
        items = []
    seen_ids: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        for key in ("id", "type", "title", "body", "created_at", "source_url", "metrics", "content_hash"):
            if key not in item:
                errors.append(f"{prefix} 缺少字段: {key}")
        if item.get("type") not in VALID_TYPES:
            errors.append(f"{prefix}.type 不受支持")
        if not str(item.get("body") or "").strip():
            errors.append(f"{prefix}.body 为空")
        if not is_http_url(item.get("source_url")):
            errors.append(f"{prefix}.source_url 不是有效 HTTP(S) URL")
        digest = str(item.get("content_hash") or "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append(f"{prefix}.content_hash 不是 64 位小写十六进制 SHA-256")
        identity = (str(item.get("type")), str(item.get("id")))
        if identity in seen_ids:
            errors.append(f"{prefix} 与前文存在重复 type/id")
        seen_ids.add(identity)
        source_url = str(item.get("source_url") or "")
        if source_url in seen_urls:
            errors.append(f"{prefix} 与前文存在重复 source_url")
        seen_urls.add(source_url)

    declared_collected = coverage.get("collected")
    declared_failed = coverage.get("failed")
    raw_errors = data.get("errors")
    if not isinstance(raw_errors, list):
        errors.append("errors 必须是数组")
        raw_errors = []
    if isinstance(declared_collected, int) and declared_collected != len(items):
        errors.append("coverage.collected 与 items 数量不一致")
    if isinstance(declared_failed, int) and declared_failed != len(raw_errors):
        errors.append("coverage.failed 与 errors 数量不一致")
    discovered = coverage.get("discovered")
    if isinstance(discovered, int) and isinstance(declared_collected, int) and isinstance(declared_failed, int):
        if discovered < declared_collected + declared_failed:
            errors.append("coverage.discovered 小于 collected + failed")
    if coverage.get("complete") is True and (raw_errors or discovered != len(items)):
        errors.append("complete=true 但仍有失败项或发现数未完全覆盖")
    return errors


def load_keywords(csv_text: str, keyword_file: Path | None) -> list[str]:
    words = [word.strip() for word in csv_text.split(",") if word.strip()]
    if keyword_file:
        words.extend(line.strip() for line in keyword_file.read_text(encoding="utf-8").splitlines() if line.strip())
    return list(dict.fromkeys(words))


def create_summary(data: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    items = data["items"]
    coverage = data["meta"]["coverage"]
    by_type = Counter(item["type"] for item in items)
    by_year = Counter(str(item["created_at"])[:4] for item in items)
    keyword_stats: dict[str, Any] = {}
    for keyword in keywords:
        evidence = []
        title_count = 0
        body_count = 0
        for item in items:
            current_title_count = item["title"].count(keyword)
            current_body_count = item["body"].count(keyword)
            title_count += current_title_count
            body_count += current_body_count
            if (current_title_count or current_body_count) and len(evidence) < 5:
                evidence.append(
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "created_at": item["created_at"],
                        "source_url": item["source_url"],
                    }
                )
        keyword_stats[keyword] = {
            "title_count": title_count,
            "body_count": body_count,
            "item_count": sum(1 for item in items if keyword in item["title"] or keyword in item["body"]),
            "evidence": evidence,
        }
    dates = [item["created_at"] for item in items]
    return {
        "schema_version": data["schema_version"],
        "author": data["author"],
        "coverage": coverage,
        "sample": {
            "total_items": len(items),
            "total_characters": sum(len(item["title"]) + len(item["body"]) for item in items),
            "by_type": dict(sorted(by_type.items())),
            "by_year": dict(sorted(by_year.items())),
            "start": min(dates) if dates else None,
            "end": max(dates) if dates else None,
        },
        "keywords": keyword_stats,
        "source_index": [
            {
                "id": item["id"],
                "type": item["type"],
                "title": item["title"],
                "created_at": item["created_at"],
                "source_url": item["source_url"],
            }
            for item in items
        ],
        "limitations": [error["reason"] for error in data["errors"]],
    }


def to_markdown(summary: dict[str, Any]) -> str:
    author = summary["author"]
    coverage = summary["coverage"]
    sample = summary["sample"]
    lines = [
        f"# {author.get('name') or author.get('url_token') or '创作者'}语料统计摘要",
        "",
        f"- 成功条目：{coverage['collected']}",
        f"- 失败条目：{coverage['failed']}",
        f"- 完整性：{'完整' if coverage['complete'] else '不完整'}",
        f"- 时间跨度：{sample['start'] or '无'} 至 {sample['end'] or '无'}",
        "",
        "## 内容类型",
        "",
        "| 类型 | 数量 |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in sample["by_type"].items())
    lines.extend(["", "## 关键词证据", "", "| 关键词 | 标题次数 | 正文次数 | 涉及条目 |", "|---|---:|---:|---:|"])
    for keyword, stat in summary["keywords"].items():
        safe_keyword = keyword.replace("|", "\\|")
        lines.append(
            f"| {safe_keyword} | {stat['title_count']} | {stat['body_count']} | {stat['item_count']} |"
        )
    if summary["limitations"]:
        lines.extend(["", "## 已知限制", ""])
        lines.extend(f"- {reason}" for reason in summary["limitations"])
    lines.extend(["", "> 统计只用于发现候选主题；观点结论仍需逐条核对来源语义。", ""])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="corpus JSON 路径")
    parser.add_argument("--keywords", default="", help="逗号分隔关键词")
    parser.add_argument("--keyword-file", type=Path, help="UTF-8 关键词文件，每行一个")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="输出路径；默认打印到 stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        validation_errors = validate_corpus(data)
        if validation_errors:
            for error in validation_errors:
                print(f"校验失败: {error}", file=sys.stderr)
            return 2
        summary = create_summary(data, load_keywords(args.keywords, args.keyword_file))
        rendered = json.dumps(summary, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else to_markdown(summary)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"分析失败: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
