from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")


def _slugify(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"\s+#*$", "", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"[^a-z0-9\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def _collect_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        heading = match.group(2).strip()
        slug = _slugify(heading)
        if not slug:
            continue
        count = counts.get(slug, 0)
        if count:
            anchor = f"{slug}-{count}"
        else:
            anchor = slug
        counts[slug] = count + 1
        anchors.add(anchor)
    return anchors


def _iter_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "wiki" / "DATA_DICTIONARY.md"]
    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        files.extend(sorted(docs_dir.rglob("*.md")))
    arch_dir = ROOT / "arch"
    if arch_dir.exists():
        files.extend(sorted(arch_dir.rglob("*.md")))
    return [path for path in files if path.exists()]


def _normalize_link(link: str) -> str:
    target = link.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if " " in target:
        target = target.split(" ", 1)[0]
    return target


def _is_external(link: str) -> bool:
    return link.startswith(("http://", "https://", "mailto:"))


def _resolve_path(current: Path, target: str) -> Path:
    if target.startswith("/"):
        return (ROOT / target.lstrip("/")).resolve()
    return (current.parent / target).resolve()


def main() -> int:
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}

    for path in _iter_files():
        anchors = _collect_anchors(path)
        anchor_cache[path.resolve()] = anchors
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for raw_link in LINK_RE.findall(line):
                target = _normalize_link(raw_link)
                if not target or _is_external(target):
                    continue

                if target.startswith("#"):
                    anchor = target[1:]
                    if anchor not in anchors:
                        errors.append(f"{path}:{line_no} broken anchor {target}")
                    continue

                file_part, anchor_part = (target.split("#", 1) + [""])[:2]
                target_path = _resolve_path(path, file_part)
                if not target_path.exists():
                    errors.append(f"{path}:{line_no} missing file {file_part}")
                    continue

                if anchor_part:
                    if target_path.suffix != ".md":
                        errors.append(
                            f"{path}:{line_no} anchor on non-markdown file {file_part}"
                        )
                        continue
                    target_path = target_path.resolve()
                    target_anchors = anchor_cache.get(target_path)
                    if target_anchors is None:
                        target_anchors = _collect_anchors(target_path)
                        anchor_cache[target_path] = target_anchors
                    if anchor_part not in target_anchors:
                        errors.append(
                            f"{path}:{line_no} broken anchor #{anchor_part} in {file_part}"
                        )

    if errors:
        print("Broken documentation links/anchors found:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
