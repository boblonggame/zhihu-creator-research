#!/usr/bin/env python3
"""验证发布包结构、Skill 元数据、测试 fixture 与公开边界。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def split_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("缺少 YAML frontmatter")
    try:
        raw, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("frontmatter 未正确结束") from exc
    metadata = yaml.safe_load(raw)
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter 必须是对象")
    return metadata, body


def validate() -> list[str]:
    problems: list[str] = []
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"无法读取插件清单: {exc}"]

    version = manifest.get("version", "")
    if not SEMVER.fullmatch(version):
        problems.append("plugin.json version 不是严格 semver")
    for dotted_key in ("name", "description", "author.name", "interface.displayName", "interface.shortDescription", "interface.longDescription", "interface.developerName", "interface.category"):
        value = manifest
        for key in dotted_key.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if not value:
            problems.append(f"plugin.json 缺少真实字段: {dotted_key}")
    if manifest.get("license") != "Apache-2.0" or not (ROOT / "LICENSE").is_file():
        problems.append("发布包必须包含 Apache-2.0 LICENSE")

    skill_root = ROOT / "skills"
    skill_dirs = sorted(path for path in skill_root.iterdir() if path.is_dir())
    expected = {"zhihu-public-content-collector", "creator-content-analyzer"}
    if {path.name for path in skill_dirs} != expected:
        problems.append("skills/ 必须且只能包含两个正式 Skill")

    allowed_frontmatter = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    for skill_dir in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        try:
            frontmatter, body = split_frontmatter(skill_file)
        except Exception as exc:
            problems.append(f"{skill_dir.name}/SKILL.md: {exc}")
            continue
        unknown = sorted(set(frontmatter) - allowed_frontmatter)
        if unknown:
            problems.append(f"{skill_dir.name}: 非标准 frontmatter 字段 {unknown}")
        if frontmatter.get("name") != skill_dir.name or not KEBAB.fullmatch(skill_dir.name):
            problems.append(f"{skill_dir.name}: name 与目录不一致或不是 kebab-case")
        description = str(frontmatter.get("description") or "")
        if len(description) < 30 or "使用" not in description:
            problems.append(f"{skill_dir.name}: description 未充分说明用途和触发时机")
        if frontmatter.get("license") != "Apache-2.0":
            problems.append(f"{skill_dir.name}: license 必须是 Apache-2.0")
        metadata = frontmatter.get("metadata")
        if not isinstance(metadata, dict) or str(metadata.get("version")) != version:
            problems.append(f"{skill_dir.name}: metadata.version 必须与发布包一致")
        if body.count("\n") + 1 > 500:
            problems.append(f"{skill_dir.name}: SKILL.md 超过 500 行")

        openai_path = skill_dir / "agents" / "openai.yaml"
        try:
            openai_data = yaml.safe_load(openai_path.read_text(encoding="utf-8"))
            interface = openai_data["interface"]
            short_description = interface["short_description"]
            default_prompt = interface["default_prompt"]
            if not 25 <= len(short_description) <= 64:
                problems.append(f"{skill_dir.name}: short_description 必须为 25-64 字符")
            if f"${skill_dir.name}" not in default_prompt:
                problems.append(f"{skill_dir.name}: default_prompt 必须显式提及 ${skill_dir.name}")
        except Exception as exc:
            problems.append(f"{skill_dir.name}/agents/openai.yaml 无效: {exc}")

        for relative in re.findall(r"\]\(([^)]+)\)", body):
            if relative.startswith(("http://", "https://", "#")) or relative.startswith("$"):
                continue
            if not (skill_dir / relative).resolve().is_file():
                problems.append(f"{skill_dir.name}: 引用文件不存在 {relative}")

    schema_path = ROOT / "skills" / "creator-content-analyzer" / "references" / "corpus-schema.json"
    fixture_path = ROOT / "tests" / "fixtures" / "sample-corpus.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validation_errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(fixture))
        problems.extend(f"sample-corpus.json: {error.message}" for error in validation_errors)
    except Exception as exc:
        problems.append(f"corpus schema 或 fixture 无效: {exc}")

    try:
        evals = json.loads((ROOT / "tests" / "evals.json").read_text(encoding="utf-8"))["cases"]
        positive = [case for case in evals if case.get("type") == "positive"]
        negative = [case for case in evals if case.get("type") == "negative"]
        if len(positive) < 5 or len(negative) < 3:
            problems.append("行为测试至少需要 5 个正向和 3 个负向案例")
        if any(not case.get("prompt") or not case.get("expectations") for case in evals):
            problems.append("每个行为测试都必须包含 prompt 和 expectations")
    except Exception as exc:
        problems.append(f"tests/evals.json 无效: {exc}")

    private_path_marker = "/" + "Users/"
    secret_patterns = [
        re.compile(r"z_c0\s*="),
        re.compile(r"Bearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml", ".txt"} and path.name not in {"LICENSE", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(ROOT)
        if private_path_marker in text:
            problems.append(f"{relative}: 包含本机绝对用户路径")
        for pattern in secret_patterns:
            if pattern.search(text):
                problems.append(f"{relative}: 疑似包含凭证值")
    return problems


def main() -> int:
    problems = validate()
    if problems:
        print("发布包校验失败：", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("发布包结构、元数据、schema、fixture 和公开边界校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
