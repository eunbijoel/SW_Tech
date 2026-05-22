"""저장 대화 목록 — 요약 제목, 중복 제거, 메타 추출."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

RESULTS_DIR = Path("./results")

_TITLE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("df_0", "df_1", "df_2", "출처 컬럼"), "다중 파일 통합"),
    (("병합", "통합", "합치", "concat", "묶어"), "파일 병합"),
    (("집행률", "집행 계", "예산 대비"), "집행률 계산"),
    (("범위", "라인", "행", "열", "구조", "컬럼", "채워"), "파일 구조/범위"),
    (("차트", "그래프", "시각화", "plot", "막대"), "차트 시각화"),
    (("분석", "패턴", "트렌드"), "데이터 분석"),
    (("필터", "추출", "상위", "하위"), "데이터 필터"),
    (("요약", "정리", "개요"), "요약 정리"),
)

_MAX_TITLE_LEN = 32


def _normalize_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def summarize_prompt_title(prompt: str, *, max_len: int = _MAX_TITLE_LEN) -> str:
    """긴 프롬프트 → 짧은 요약 제목."""
    t = _normalize_prompt(prompt)
    if not t:
        return "새 대화"
    low = t.lower()
    for keywords, label in _TITLE_RULES:
        if any(kw in t or kw in low for kw in keywords):
            return label
    for sep in (".", "?", "!", "。", "？", "！"):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
            break
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def first_user_prompt_from_messages(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        trace = msg.get("trace") or {}
        text = trace.get("user_prompt") or msg.get("content") or ""
        text = _normalize_prompt(text)
        if text:
            return text
    return ""


def chat_fingerprint(messages: list[dict] | None = None, *, first_prompt: str = "") -> str:
    """동일 주제 중복 판별용."""
    base = first_prompt or (first_user_prompt_from_messages(messages or []) if messages else "")
    base = _normalize_prompt(base)
    if not base:
        return ""
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def parse_title_from_markdown(text: str) -> str:
    for line in text.splitlines()[:12]:
        m = re.match(r"^title:\s*(.+)\s*$", line, re.I)
        if m:
            return m.group(1).strip()
    return ""


def title_for_chat_file(path: Path, *, load_messages_fn) -> str:
    """파일에서 title 메타 또는 첫 사용자 메시지로 제목 생성."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    meta = parse_title_from_markdown(raw)
    if meta:
        return meta
    try:
        messages = load_messages_fn(path)
        prompt = first_user_prompt_from_messages(messages)
        if prompt:
            return summarize_prompt_title(prompt)
    except Exception:
        pass
    return path.stem.replace("chat_", "").replace("_", " ")


def is_live_autosave_file(name: str) -> bool:
    return name.startswith("chat_live_")


def dedupe_chat_items(items: list[dict]) -> list[dict]:
    """동일 fingerprint → 최신 mtime 1건만."""
    best: dict[str, dict] = {}
    for item in items:
        fp = item.get("fingerprint") or ""
        if not fp:
            best[item["name"]] = item
            continue
        prev = best.get(fp)
        if prev is None or item["mtime"] > prev["mtime"]:
            best[fp] = item
    out = list(best.values())
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def prune_duplicate_chat_files(items: list[dict], *, results_dir: Path | None = None) -> int:
    """디스크에서 fingerprint 중복 파일 삭제 (최신 1개만 유지)."""
    root = results_dir or RESULTS_DIR
    by_fp: dict[str, list[dict]] = {}
    for item in items:
        if is_live_autosave_file(item["name"]):
            continue
        fp = item.get("fingerprint") or ""
        if not fp:
            continue
        by_fp.setdefault(fp, []).append(item)
    removed = 0
    for group in by_fp.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x["mtime"], reverse=True)
        for stale in group[1:]:
            try:
                (root / stale["name"]).unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
    return removed


def format_chat_list_label(item: dict) -> str:
    """사이드바 한 줄: `05/22 16:27 · 파일 병합`"""
    mtime: datetime = item["mtime"]
    ts = mtime.strftime("%m/%d %H:%M")
    title = item.get("title") or item.get("preview") or item.get("name", "")
    turns = item.get("turns")
    if turns and turns > 1:
        return f"{ts} · {title} ({turns}턴)"
    return f"{ts} · {title}"


def format_step_select_label(item: dict) -> str:
    """Step Flow selectbox — 요약 제목만 (시간은 짧게)."""
    title = item.get("title") or item.get("name", "")
    mtime: datetime = item["mtime"]
    return f"{mtime.strftime('%m/%d %H:%M')} · {title}"


def build_chat_item(
    path: Path,
    *,
    load_messages_fn: Optional[Callable[[Path], list]] = None,
    include_live: bool = False,
) -> Optional[dict[str, Any]]:
    from services.conversation_store import markdown_to_messages

    name = path.name
    if not include_live and is_live_autosave_file(name):
        return None
    try:
        stat = path.stat()
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if load_messages_fn:
        messages = load_messages_fn(path)
    else:
        messages = markdown_to_messages(raw)
    first = first_user_prompt_from_messages(messages)
    title = parse_title_from_markdown(raw)
    if not title:
        title = summarize_prompt_title(first) if first else name
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    return {
        "name": name,
        "path": path.resolve(),
        "mtime": datetime.fromtimestamp(stat.st_mtime),
        "size": stat.st_size,
        "title": title,
        "preview": title,
        "fingerprint": chat_fingerprint(first_prompt=first),
        "turns": user_turns,
        "first_prompt": first,
    }
