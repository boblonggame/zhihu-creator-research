#!/usr/bin/env python3
"""把知乎页面或同源 JSON 批次规整为 Creator Content Corpus 1.0.0。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0.0"
VALID_TYPES = {"answer", "article", "pin", "other"}
TYPE_ALIASES = {
    "answers": "answer",
    "articles": "article",
    "post": "article",
    "posts": "article",
    "pins": "pin",
    "moment": "pin",
    "moments": "pin",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"p", "br", "div", "li", "blockquote", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"p", "div", "li", "blockquote", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\u200b", "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_datetime(value: Any) -> str:
    if value is None or value == "":
        raise ValueError("缺少发布时间")
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    raw = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        parsed_date = date.fromisoformat(raw)
        return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"非法日期: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_type(value: Any, hint: str = "") -> str:
    raw = str(value or hint or "other").strip().lower()
    normalized = TYPE_ALIASES.get(raw, raw)
    return normalized if normalized in VALID_TYPES else "other"


def infer_type_hint(path: Path) -> str:
    lowered = path.name.lower()
    for token in ("answer", "article", "post", "pin", "moment"):
        if token in lowered:
            return normalize_type(token)
    return "other"


def as_nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def first_value(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def extract_items(payload: Any) -> tuple[list[Any], list[dict[str, str]]]:
    if isinstance(payload, list):
        return payload, []
    if not isinstance(payload, dict):
        return [], [{"source": "payload", "type": "unknown", "reason": "顶层 JSON 必须是对象或数组"}]
    for key in ("data", "items", "results"):
        if isinstance(payload.get(key), list):
            raw_errors = payload.get("errors", [])
            errors = [error for error in raw_errors if isinstance(error, dict)] if isinstance(raw_errors, list) else []
            return payload[key], errors
    if all(key in payload for key in ("id",)):
        return [payload], []
    return [], [{"source": "payload", "type": "unknown", "reason": "找不到 data、items 或 results 数组"}]


def normalize_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("缺少有效来源 URL")
    return url


def normalize_item(raw: Any, type_hint: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("内容条目不是 JSON 对象")
    question = raw.get("question") if isinstance(raw.get("question"), dict) else {}
    item_type = normalize_type(first_value(raw, "type", "content_type"), type_hint)
    title = clean_text(first_value(raw, "title", "name") or question.get("title") or "")
    body = clean_text(first_value(raw, "body", "content", "content_text", "excerpt", "description"))
    if not body:
        raise ValueError("缺少正文；列表摘要不可冒充完整内容")
    source_url = normalize_url(first_value(raw, "source_url", "url", "canonical_url", "link"))
    created_at = normalize_datetime(first_value(raw, "created_at", "created_time", "created", "published_at", "date"))
    raw_id = first_value(raw, "id", "content_id", "token")
    item_id = str(raw_id).strip() if raw_id is not None else hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:24]
    digest_source = json.dumps(
        {"type": item_type, "title": title, "body": body, "created_at": created_at, "source_url": source_url},
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "id": item_id,
        "type": item_type,
        "title": title,
        "body": body,
        "created_at": created_at,
        "source_url": source_url,
        "metrics": {
            "voteup": as_nonnegative_int(first_value(raw, "voteup", "voteup_count", "vote_count")),
            "comment": as_nonnegative_int(first_value(raw, "comment", "comment_count")),
            "favorite": as_nonnegative_int(first_value(raw, "favorite", "favorite_count")),
        },
        "content_hash": hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
    }


def normalize_error(raw: dict[str, Any], fallback_type: str) -> dict[str, str]:
    return {
        "source": str(first_value(raw, "source", "url", "id") or "unknown"),
        "type": normalize_type(first_value(raw, "type", "content_type"), fallback_type),
        "reason": str(first_value(raw, "reason", "message", "error") or "未说明的采集失败"),
    }


def build_corpus(
    input_paths: Iterable[Path],
    profile_url: str,
    author_name: str,
    platform: str,
    collection_method: str,
    complete: bool,
    discovered: int | None,
    coverage_note: str,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()

    for path in input_paths:
        hint = infer_type_hint(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"source": str(path), "type": hint, "reason": f"无法读取 JSON: {exc}"})
            continue
        raw_items, raw_errors = extract_items(payload)
        errors.extend(normalize_error(error, hint) for error in raw_errors)
        for index, raw in enumerate(raw_items):
            try:
                item = normalize_item(raw, hint)
            except ValueError as exc:
                source = str(raw.get("url") or raw.get("id") or f"{path.name}#{index}") if isinstance(raw, dict) else f"{path.name}#{index}"
                failed_type = normalize_type(first_value(raw, "type", "content_type"), hint) if isinstance(raw, dict) else hint
                errors.append({"source": source, "type": failed_type, "reason": str(exc)})
                continue
            key = f"{platform}:{item['type']}:{item['id']}"
            alternate_key = f"url:{item['source_url']}"
            if key in seen or alternate_key in seen:
                continue
            seen.update({key, alternate_key})
            normalized.append(item)

    normalized.sort(key=lambda item: (item["created_at"], item["type"], item["id"]))
    requested_types = sorted({item["type"] for item in normalized} | {error["type"] for error in errors if error["type"] != "unknown"})
    timestamps = [item["created_at"] for item in normalized]
    failed = len(errors)
    minimum_discovered = len(normalized) + failed
    discovered_count = discovered if discovered is not None else minimum_discovered
    if discovered_count < minimum_discovered:
        raise ValueError("--discovered 不能小于成功数与失败数之和")
    if discovered_count > minimum_discovered and not coverage_note:
        coverage_note = "平台发现数大于已处理数，存在尚未枚举或未记录的条目。"
    if complete and (failed or discovered_count != len(normalized)):
        complete = False
        coverage_note = coverage_note or "存在失败项或发现数未完全覆盖，已自动将 complete 设为 false。"

    token = urlparse(profile_url).path.rstrip("/").split("/")[-1]
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "platform": platform,
            "source_profile_url": normalize_url(profile_url),
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "collection_method": collection_method,
            "requested_types": requested_types,
            "time_range": {
                "start": min(timestamps) if timestamps else None,
                "end": max(timestamps) if timestamps else None,
            },
            "coverage": {
                "discovered": discovered_count,
                "collected": len(normalized),
                "failed": failed,
                "complete": complete,
                "note": coverage_note,
            },
        },
        "author": {"name": author_name, "url_token": token, "profile_url": profile_url},
        "items": normalized,
        "errors": errors,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="一个或多个原始 JSON 批次")
    parser.add_argument("--profile-url", required=True, help="目标知乎创作者主页 URL")
    parser.add_argument("--author-name", default="", help="页面显示的创作者昵称")
    parser.add_argument("--platform", default="zhihu", help="平台标识，默认 zhihu")
    parser.add_argument("--collection-method", default="authenticated-browser", help="采集方式说明")
    parser.add_argument("--discovered", type=int, help="平台发现总数；不填则按成功数加失败数计算")
    parser.add_argument("--complete", action="store_true", help="确认所有请求类型到达可验证末页")
    parser.add_argument("--coverage-note", default="", help="覆盖率限制或停止原因")
    parser.add_argument("--output", required=True, type=Path, help="corpus JSON 输出路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        corpus = build_corpus(
            args.inputs,
            args.profile_url,
            args.author_name,
            args.platform,
            args.collection_method,
            args.complete,
            args.discovered,
            args.coverage_note,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"规整失败: {exc}", file=sys.stderr)
        return 2
    coverage = corpus["meta"]["coverage"]
    print(
        f"已写入 {args.output}：成功 {coverage['collected']}，失败 {coverage['failed']}，完整性 {coverage['complete']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
