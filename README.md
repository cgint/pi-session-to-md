# pi-session-to-md

Convert a `pi-coding-agent` session JSONL file into **conversation-first Markdown**.

This tool focuses on readable chat output (USER + ASSISTANT + optional THINKING), unlike app-shell HTML exports and unlike debug-heavy exports.

It is built for session files produced by [`pi-mono`](https://github.com/badlogic/pi-mono).

---

## Is this tool for me?

**Use it when you want:**

- clean, readable conversation transcripts for sharing
- markdown you can paste into GitHub/GitLab discussions
- optional inclusion of assistant thinking for deeper review

**Not ideal when you want:**

- pixel-accurate UI replay of the original Pi session
- raw debugging/event logs for low-level diagnostics

---

## What it does

Given a Pi session file (`*.jsonl`), it produces Markdown suitable for:

- GitHub / GitLab issues and discussions
- sharing conversation context with teammates
- archiving sessions in docs repositories

It can:

- export the **full session** or a **single branch** (`parentId` chain)
- include or omit assistant thinking blocks
- include bash execution messages as system sections
- include timestamps
- group consecutive messages by role to reduce heading noise

---

## Requirements

- Python **3.9+**
- No third-party runtime dependencies (stdlib only)

---

## Quick start

### 1) Clone

```bash
git clone https://github.com/cgint/pi-session-to-md.git
cd pi-session-to-md
```

### 2) Run directly

```bash
python3 pi_session_to_md.py /path/to/session.jsonl -o session.md
```

### 3) Or use the included CLI wrapper

```bash
./pi-session-to-md /path/to/session.jsonl -o session.md
```

---

## Usage

```bash
python3 pi_session_to_md.py INPUT_JSONL [options]
```

### Options

- `-o, --output PATH` output file path (`-` for stdout, default: `-`)
- `--mode {all,branch}` export full file or one parent chain (default: `all`)
- `--leaf ID` leaf id used by branch mode (default: last message id)
- `--no-thinking` omit assistant thinking blocks
- `--include-bash` include `bashExecution` messages as system blocks
- `--timestamps` include timestamps in output
- `--no-group-turns` disable role-based turn grouping

---

## Examples

### Export full session

```bash
python3 pi_session_to_md.py ~/.pi/agent/sessions/abc/session.jsonl -o session.md
```

### Export selected branch only

```bash
python3 pi_session_to_md.py ~/.pi/agent/sessions/abc/session.jsonl \
  --mode branch \
  --leaf msg_12345 \
  -o branch.md
```

### Export without thinking

```bash
python3 pi_session_to_md.py ~/.pi/agent/sessions/abc/session.jsonl --no-thinking -o clean.md
```

### Stream to stdout

```bash
python3 pi_session_to_md.py ~/.pi/agent/sessions/abc/session.jsonl -o -
```

---

## Input format expectations

- newline-delimited JSON records (`.jsonl`)
- records similar to Pi session logs with `type`, `id`, `parentId`, `timestamp`, and message payloads

The converter is tolerant and skips unknown/non-conversation record types.

---

## Branch mode note

`--mode branch` reconstructs one chain by following `parentId` from the selected leaf back to root.

It is a **best-effort approximation** and can differ from what the UI shows in some edge cases.

---

## Install as a local command (optional)

```bash
chmod +x pi-session-to-md
ln -s "$(pwd)/pi-session-to-md" ~/.local/bin/pi-session-to-md
```

---

## Development

Run help:

```bash
python3 pi_session_to_md.py --help
```

No dependency install step is required for runtime.

---

## License

MIT (see [LICENSE](./LICENSE)).
