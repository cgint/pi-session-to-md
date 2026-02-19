#!/usr/bin/env python3
"""Convert a pi-coding-agent session JSONL file to *conversation-first* Markdown.

Why this exists:
- `pi --export` / HTML exports are JS app-shell pages, not static HTML.
- `pi-md-export` is great for debugging, but can be tool-noisy.
- This script focuses on the conversation: USER + ASSISTANT + THINKING (use `--no-thinking` to omit).

Input format:
- A Pi session file (`*.jsonl`) as stored under `~/.pi/agent/sessions/.../*.jsonl`.

Output:
- Markdown suitable for GitHub/GitLab.

Notes:
- "branch" mode reconstructs a single parentId chain from a leaf id.
  It is a best-effort approximation of the currently selected branch in the Pi UI.
- Turn grouping merges consecutive messages by role (USER/ASSISTANT) to reduce heading spam.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclasses.dataclass
class SessionMeta:
    session_id: str = ""
    started_at: Optional[_dt.datetime] = None
    cwd: str = ""


def _parse_iso(ts: Any) -> Optional[_dt.datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    # Pi timestamps look like: 2026-02-19T08:37:11.936Z
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(ts)
    except Exception:
        return None


def _read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON on line {line_no}: {e}") from e
            if isinstance(obj, dict):
                yield obj


def _extract_text_and_thinking_from_content(content: Any) -> Tuple[str, str]:
    """Return (text, thinking) from a Pi message content payload."""

    text_parts: List[str] = []
    thinking_parts: List[str] = []

    if isinstance(content, str):
        if content.strip():
            text_parts.append(content.strip())
        return ("\n\n".join(text_parts).strip(), "\n\n".join(thinking_parts).strip())

    if not isinstance(content, list):
        return ("", "")

    for item in content:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "text":
            t = item.get("text")
            if isinstance(t, str) and t.strip():
                text_parts.append(t.strip())
        elif itype == "thinking":
            t = item.get("thinking")
            if isinstance(t, str) and t.strip():
                thinking_parts.append(t.strip())
        else:
            # ignore toolCall, images, etc.
            continue

    return ("\n\n".join(text_parts).strip(), "\n\n".join(thinking_parts).strip())


def _blockquote(text: str) -> str:
    """Render text as a Markdown blockquote, preserving blank lines *within* the text."""

    out_lines: List[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            out_lines.append(">")
        else:
            out_lines.append("> " + line)
    return "\n".join(out_lines)


def _format_thinking(thinking: str, style: str) -> str:
    """Return markdown for a single assistant thinking block.

    `style` is intentionally limited to:
    - `details` (default)
    - `omit`
    """

    if not thinking.strip() or style == "omit":
        return ""

    # details: keep thinking as Markdown, but inside a blockquote so it is visually separated.
    # (Blank lines *between* multiple thinking parts are handled by the caller by starting a new
    # blockquote, so the separator line can be truly empty without a leading ">".)
    t = thinking.rstrip()
    qt = _blockquote(t)
    return (
        "<details>\n"
        "<summary>thinking</summary>\n\n"
        f"{qt}\n\n"
        "</details>"
    )


def _format_group(
    *,
    role: str,
    text: str,
    thinking_blocks: List[str],
    thinking_style: str,
    include_timestamps: bool,
    ts_first: Optional[_dt.datetime],
    ts_last: Optional[_dt.datetime],
) -> str:
    role_label = "USER" if role == "user" else "ASSISTANT"

    lines: List[str] = []
    lines.append(f"### {role_label}")
    lines.append("")

    if include_timestamps and ts_first:
        if ts_last and ts_last != ts_first:
            lines.append(f"_timestamps: {ts_first.isoformat()} … {ts_last.isoformat()}_")
        else:
            lines.append(f"_timestamp: {ts_first.isoformat()}_")
        lines.append("")

    if text.strip():
        lines.append(text.rstrip())
    else:
        # Keep assistant blocks that contain only thinking (no filler).
        if role == "user" and not thinking_blocks:
            lines.append("(no content)")
        elif role == "assistant" and not thinking_blocks:
            lines.append("(no content)")

    if role == "assistant":
        if thinking_style == "details":
            # Group all thinking parts into a single <details> section.
            # Each original thinking part becomes its own blockquote; we separate parts with a
            # *truly empty line* (no leading ">") by ending the blockquote and starting a new one.
            parts = [_blockquote(tb.rstrip()) for tb in thinking_blocks if tb.strip()]
            if parts:
                body = "\n\n".join(parts)
                t_block = (
                    "<details>\n"
                    "<summary>thinking</summary>\n\n"
                    f"{body}\n\n"
                    "</details>"
                )
                lines.append(t_block)
                lines.append("")
        else:
            for tb in thinking_blocks:
                t_block = _format_thinking(tb, thinking_style)
                if t_block:
                    lines.append(t_block)
                    lines.append("")

    lines.append("")
    return "\n".join(lines)


def _build_id_index(records: Iterable[Dict[str, Any]]) -> Tuple[SessionMeta, List[str], Dict[str, Dict[str, Any]]]:
    meta = SessionMeta()
    order: List[str] = []
    by_id: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        rtype = rec.get("type")
        if rtype == "session":
            rec_id = rec.get("id")
            if isinstance(rec_id, str):
                meta.session_id = rec_id

            meta.started_at = _parse_iso(rec.get("timestamp")) or meta.started_at

            rec_cwd = rec.get("cwd")
            if isinstance(rec_cwd, str):
                meta.cwd = rec_cwd

        rid = rec.get("id")
        if isinstance(rid, str) and rid:
            order.append(rid)
            by_id[rid] = rec

    return meta, order, by_id


def _resolve_leaf_id(order: List[str], by_id: Dict[str, Dict[str, Any]], leaf: Optional[str]) -> Optional[str]:
    if leaf:
        return leaf if leaf in by_id else None

    # Prefer last message entry, else fall back to last record id.
    for rid in reversed(order):
        rec = by_id.get(rid)
        if not rec:
            continue
        if rec.get("type") == "message":
            return rid

    return order[-1] if order else None


def _collect_branch_chain(leaf_id: str, by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    chain: List[str] = []
    seen: set[str] = set()

    cur: Optional[str] = leaf_id
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        rec = by_id.get(cur)
        if not rec:
            break
        parent = rec.get("parentId")
        cur = parent if isinstance(parent, str) and parent else None

    chain.reverse()
    return chain


def generate_markdown(
    *,
    input_jsonl: str,
    mode: str,
    leaf_id: Optional[str],
    thinking_style: str,
    include_bash: bool,
    include_timestamps: bool,
    group_turns: bool,
) -> str:
    records = list(_read_jsonl(input_jsonl))
    meta, order, by_id = _build_id_index(records)

    if mode not in ("all", "branch"):
        raise ValueError(f"Invalid mode: {mode}")

    selected_records: List[Dict[str, Any]] = []
    branch_info = ""

    if mode == "all":
        selected_records = records
    else:
        leaf = _resolve_leaf_id(order, by_id, leaf_id)
        if not leaf:
            raise RuntimeError("Could not resolve leaf id (empty file?)")
        chain_ids = _collect_branch_chain(leaf, by_id)
        selected_records = [by_id[rid] for rid in chain_ids if rid in by_id]
        branch_info = f"leaf: {leaf}"

    out: List[str] = []

    title = os.path.basename(input_jsonl)
    out.append(f"# PI session (conversation) — {title}")
    out.append("")
    if meta.session_id:
        out.append(f"- id: `{meta.session_id}`")
    if meta.started_at:
        out.append(f"- started: `{meta.started_at.isoformat()}`")
    if meta.cwd:
        out.append(f"- cwd: `{meta.cwd}`")
    out.append(f"- source: `{input_jsonl}`")
    out.append(f"- mode: `{mode}`")
    if branch_info:
        out.append(f"- {branch_info}")
    out.append(f"- thinking: `{thinking_style}`")
    out.append(f"- group_turns: `{'on' if group_turns else 'off'}`")
    if include_timestamps:
        out.append("- timestamps: `on`")
    out.append("")
    out.append("---")
    out.append("")

    # Turn grouping state
    cur_role: Optional[str] = None
    cur_text_parts: List[str] = []
    cur_thinking_parts: List[str] = []
    cur_ts_first: Optional[_dt.datetime] = None
    cur_ts_last: Optional[_dt.datetime] = None

    def flush() -> None:
        nonlocal cur_role, cur_text_parts, cur_thinking_parts, cur_ts_first, cur_ts_last
        if not cur_role:
            return

        text = "\n\n".join([t for t in cur_text_parts if t.strip()]).strip()
        thinking_blocks = [t for t in cur_thinking_parts if t.strip()]

        # Skip empty blocks
        if cur_role == "user" and not text:
            pass
        elif cur_role == "assistant" and not text and not thinking_blocks:
            pass
        else:
            out.append(
                _format_group(
                    role=cur_role,
                    text=text,
                    thinking_blocks=thinking_blocks,
                    thinking_style=thinking_style,
                    include_timestamps=include_timestamps,
                    ts_first=cur_ts_first,
                    ts_last=cur_ts_last,
                ).rstrip()
            )
            out.append("")

        cur_role = None
        cur_text_parts = []
        cur_thinking_parts = []
        cur_ts_first = None
        cur_ts_last = None

    for rec in selected_records:
        if rec.get("type") != "message":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue

        role = msg.get("role")

        if role not in ("user", "assistant"):
            if role == "bashExecution" and include_bash:
                # keep bashExecution as its own SYSTEM block; it breaks grouping intentionally
                flush()
                cmd = msg.get("command")
                output = msg.get("output")

                parts: List[str] = []
                parts.append("### SYSTEM (bashExecution)")
                parts.append("")
                if include_timestamps:
                    ts = _parse_iso(rec.get("timestamp"))
                    if ts:
                        parts.append(f"_timestamp: {ts.isoformat()}_")
                        parts.append("")
                if isinstance(cmd, str) and cmd.strip():
                    parts.append("Command:")
                    parts.append("```bash")
                    parts.append(cmd.rstrip())
                    parts.append("```")
                    parts.append("")
                if isinstance(output, str) and output.strip():
                    parts.append("Output:")
                    parts.append("```text")
                    parts.append(output.rstrip("\n"))
                    parts.append("```")
                    parts.append("")
                out.append("\n".join(parts).rstrip())
                out.append("")
            continue

        text, thinking = _extract_text_and_thinking_from_content(msg.get("content"))

        # Skip empty user/assistant messages unless assistant has thinking
        if role == "user" and not text.strip():
            continue
        if role == "assistant" and not text.strip() and not thinking.strip():
            continue

        ts = _parse_iso(rec.get("timestamp"))

        if not group_turns:
            flush()
            out.append(
                _format_group(
                    role=role,
                    text=text,
                    thinking_blocks=[thinking] if thinking.strip() else [],
                    thinking_style=thinking_style,
                    include_timestamps=include_timestamps,
                    ts_first=ts,
                    ts_last=ts,
                ).rstrip()
            )
            out.append("")
            continue

        # group_turns == True
        if cur_role is None:
            cur_role = role
        elif cur_role != role:
            flush()
            cur_role = role

        if ts and cur_ts_first is None:
            cur_ts_first = ts
        if ts:
            cur_ts_last = ts

        if text.strip():
            cur_text_parts.append(text.strip())
        if role == "assistant" and thinking.strip():
            cur_thinking_parts.append(thinking.strip())

    flush()

    return "\n".join(out).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Convert a Pi session JSONL to conversation-first Markdown")
    p.add_argument("input", help="Path to session .jsonl")
    p.add_argument("-o", "--output", default="-", help="Output file path (default: stdout). Use '-' for stdout.")
    p.add_argument("--mode", choices=["all", "branch"], default="all", help="Export full file or a single parentId chain")
    p.add_argument("--leaf", default=None, help="Leaf id for branch mode (defaults to last message id)")
    p.add_argument(
        "--no-thinking",
        action="store_true",
        help="Do not include assistant thinking blocks",
    )
    p.add_argument("--include-bash", action="store_true", help="Include bashExecution entries as SYSTEM blocks")
    p.add_argument("--timestamps", action="store_true", help="Include timestamps")

    p.set_defaults(group_turns=True)
    p.add_argument(
        "--no-group-turns",
        dest="group_turns",
        action="store_false",
        help="Do not merge consecutive messages by role",
    )

    args = p.parse_args(argv)

    md = generate_markdown(
        input_jsonl=args.input,
        mode=args.mode,
        leaf_id=args.leaf,
        thinking_style=("omit" if args.no_thinking else "details"),
        include_bash=bool(args.include_bash),
        include_timestamps=bool(args.timestamps),
        group_turns=bool(args.group_turns),
    )

    if args.output == "-":
        sys.stdout.write(md)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
