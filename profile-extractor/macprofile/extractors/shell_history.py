"""zsh history — extended format: ': <epoch>:<duration>;<command>'."""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from macprofile.extractors.base import Extractor, emit, stable_hash

SRC = Path.home() / ".zsh_history"

LINE_RE = re.compile(r"^:\s*(\d+):(\d+);(.*)$", re.S)


class ShellHistoryExtractor(Extractor):
    name = "shell"
    src = SRC

    def available(self) -> bool:
        return self.src.exists()

    def extract(self) -> Iterator:
        text = self.src.read_text(encoding="utf-8", errors="replace")
        # zsh joins continuation lines with backslash + newline at write time;
        # split on lines starting with ':' to be safe.
        lines: list[str] = []
        cur = ""
        for raw in text.splitlines():
            if raw.startswith(":") and cur:
                lines.append(cur)
                cur = raw
            elif raw.startswith(":"):
                cur = raw
            else:
                cur += "\n" + raw
        if cur:
            lines.append(cur)

        for ln, line in enumerate(lines):
            m = LINE_RE.match(line)
            if not m:
                continue
            epoch, duration, cmd = m.groups()
            try:
                dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
            cmd = cmd.strip()
            tool = cmd.split(maxsplit=1)[0] if cmd else ""
            yield emit(
                ts=dt,
                source="shell.zsh_history",
                category="shell_command",
                target=tool,
                target_kind="other",
                duration_sec=float(duration) if duration.isdigit() else None,
                metadata={"command": cmd, "line": ln},
                raw_hash=stable_hash("zsh", ln, epoch, cmd),
            )
