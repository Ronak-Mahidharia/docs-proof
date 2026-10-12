"""A walkthrough for someone new to docs-proof: docs/walkthrough.gif, and the same steps as text in
docs/walkthrough.md. It makes a tiny project in a temporary folder, changes its code twice, and runs every command it
shows there, so all the output in both is from a real run. docs-proof runs as `python -P -m docsproof`, the same
program as the docs-proof command. It stops if a run no longer shows what a step says about it. The GIF carries the
text page's SHA-256, so a test can tell that both come from the same run, and that a fresh run still prints the same.

    python scripts/walkthrough.py          # both; drawing the GIF needs Pillow (requirements-walkthrough.txt)
    python scripts/walkthrough.py --text   # the text page only
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "walkthrough.md"
GIF = ROOT / "docs" / "walkthrough.gif"

# The tiny project: one option, a README line about it, and a docs page with a command that uses it.
FILES = {
    "pyproject.toml": '[project]\nname = "tiny"\n\n[project.scripts]\ntiny = "tiny.cli:main"\n',
    "tiny/__init__.py": "",
    "tiny/cli.py": ("import argparse\n\n\n"
                    "def main(argv=None):\n"
                    "    parser = argparse.ArgumentParser()\n"
                    '    parser.add_argument("--limit", type=int, default=10, help="show at most N items")\n'
                    "    return parser.parse_args(argv)\n"),
    "README.md": "# tiny\n\nUse `--limit` to cap the list (default: 10).\n",
    "docs/usage.md": "Show three items:\n\n```console\n$ tiny --limit 3\n```\n",
}
# Git without anyone's own settings, and with a fixed date, so the commit's ID in docs-proof's output is the same on
# every run and every computer.
WHEN = "2026-10-11T12:00:00+00:00"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "Tiny", "GIT_AUTHOR_EMAIL": "tiny@example.com", "GIT_AUTHOR_DATE": WHEN,
       "GIT_COMMITTER_NAME": "Tiny", "GIT_COMMITTER_EMAIL": "tiny@example.com", "GIT_COMMITTER_DATE": WHEN,
       "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1"}

TITLE = "Finds the lines in your docs that a code change made wrong, and proves each one."
WAYS = [("In a terminal", "the `docs-proof` command. It uses no AI unless you ask, and sends nothing anywhere."),
        ("On every pull request", "the GitHub Action lists each flagged line, its proof, and its fix in the job "
                                  "summary."),
        ("In AI assistants", "the MCP server gives Claude Code and other assistants the same check, as two "
                             "read-only tools.")]
ALT = ("An animated walkthrough: a tiny project's option is renamed, docs-proof finds the two doc lines that still use "
       "the old name and proves each one, its fixes are saved as a patch and applied with git, and a changed default "
       "is then found the same way")


@dataclass
class Command:
    typed: str   # as the walkthrough shows it, typed at the prompt
    output: str  # what it printed, stdout and stderr in the order printed
    status: int

    @property
    def lines(self) -> list[str]:
        return self.output.rstrip("\n").split("\n") if self.output else []


@dataclass
class Note:
    text: str         # what the GIF says while it points at the lines, and a bullet on the text page
    lines: list[int]  # the lines it points at, in the step's last output


@dataclass
class Step:
    title: str
    caption: str
    commands: list[Command]
    notes: list[Note] = field(default_factory=list)


def shell(root: Path, typed: str, argv: list[str], status: int) -> Command:
    """Runs a command in the tiny project, and stops if it doesn't end the way the walkthrough says."""
    done = subprocess.run(argv, cwd=root, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if done.returncode != status:
        raise SystemExit(f"walkthrough: `{typed}` exited with status {done.returncode}, not {status}:\n{done.stdout}")
    return Command(typed, done.stdout, done.returncode)


def run_as_typed(root: Path, typed: str, status: int = 0) -> Command:
    return shell(root, typed, typed.split(), status)


def docs_proof(root: Path, *args: str, status: int) -> Command:
    return shell(root, " ".join(["docs-proof", *args]), [sys.executable, "-P", "-m", "docsproof", *args], status)


def findings(lines: list[str], count: int) -> list[list[int]]:
    """The line numbers of each finding in docs-proof's output, a block of lines that starts with file:line. Stops
    if there aren't as many as the step says."""
    blocks, block = [], []
    for number, line in enumerate([*lines, ""]):
        if line:
            block.append(number)
        elif block:
            blocks.append(block)
            block = []
    found = [b for b in blocks if re.fullmatch(r"\S+:\d+", lines[b[0]])]
    if len(found) != count:
        raise SystemExit(f"walkthrough: docs-proof found {len(found)} doc lines, not {count}:\n" + "\n".join(lines))
    return found


def labeled(lines: list[str], finding: list[int], label: str) -> list[int]:
    """The lines of a finding that start with its label, why or fix."""
    return [number for number in finding if lines[number].startswith(f"  {label}: ")]


def note(text: str, lines: list[str], pointed: list[int], shows: str) -> Note:
    """A note on a step's output, which stops the walkthrough if the lines it points at don't show what it says."""
    if not any(shows in lines[number] for number in pointed):
        raise SystemExit(f"walkthrough: the note {text!r} points at lines that don't show {shows!r}")
    return Note(text, pointed)


def write_project(root: Path) -> None:
    for name, text in FILES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    for args in (["init", "-q", "--object-format=sha1", "-b", "main"], ["add", "-A"],
                 ["commit", "-q", "-m", "A tiny project"]):
        subprocess.run(["git", *args], cwd=root, env=ENV, check=True, capture_output=True)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"walkthrough: {path.name} doesn't have exactly one {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def run() -> list[Step]:
    """Every step of the walkthrough, with the real output of each command it shows."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "tiny"
        write_project(root)
        code = root / "tiny" / "cli.py"
        steps = [Step("A tiny Python project", "Its code has one option, `--limit`, and two docs mention it.",
                      [run_as_typed(root, f"cat {name}") for name in ("tiny/cli.py", "README.md", "docs/usage.md")])]

        edit(code, '"--limit"', '"--cap"')
        steps.append(Step("A code change", "Someone renames `--limit` to `--cap`, and nobody updates the docs.",
                          [run_as_typed(root, "git diff")]))

        found = docs_proof(root, status=1)
        lines = found.lines
        first, second = findings(lines, 2)
        steps.append(Step("Run docs-proof", "It compares the code before and after the change, then reads the docs.",
                          [found], [
            note(f"First, the doc line the change made wrong: `{lines[first[0]]}`.", lines, first[:2], "--limit"),
            note("Then the proof: `--limit` was in the code before, and now it's gone.", lines,
                 labeled(lines, first, "why"), "before the change and is gone"),
            note("Then a fix: the new name, where the old one was.", lines, labeled(lines, first, "fix"), "--cap"),
            note("A command in the docs gets a second proof: `tiny` no longer has a `--limit` option.", lines,
                 labeled(lines, second, "why")[1:], "declares no --limit option"),
            note("It changed nothing. The fixes are only suggestions until you say yes.", lines, [len(lines) - 1],
                 "fixes suggested"),
        ]))

        saved = docs_proof(root, "--patch", "fixes.patch", status=1)
        lines = saved.lines
        steps.append(Step("Save the fixes", "`--patch` writes them to a file, so you can read them before anything "
                          "changes.", [saved], [
            note("The same findings, and now the fixes are in `fixes.patch`.", lines,
                 [n for n, line in enumerate(lines) if line.startswith("docs-proof: wrote ")], "fixes.patch"),
        ]))

        steps.append(Step("Read the patch, then apply it", "The patch is plain text, and `git apply` makes the "
                          "changes.", [run_as_typed(root, "cat fixes.patch"), run_as_typed(root, "git apply fixes.patch")]))

        again = docs_proof(root, status=0)
        if not again.lines[0].startswith("docs-proof: no doc line found"):
            raise SystemExit(f"walkthrough: the check after the fixes found something:\n{again.output}")
        steps.append(Step("Check again", f"Nothing is left to fix, so it exits with status {again.status}. Earlier it "
                          f"exited with {found.status}, which fails a CI check.", [again]))

        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=root, env=ENV, check=True)
        (root / "fixes.patch").unlink()
        edit(code, "default=10", "default=20")
        value = docs_proof(root, status=1)
        lines = value.lines
        (only,) = findings(lines, 1)
        steps.append(Step("Changed values too", "Starting again from the first version, the default of `--limit` goes "
                          "from 10 to 20.", [value], [
            note("The proof quotes the code line with the new default, and the fix shows the new value.", lines,
                 labeled(lines, only, "why") + labeled(lines, only, "fix"), "default=20"),
        ]))
    return steps


def fence(text: str) -> str:
    """A code fence longer than any run of backticks in the text, so the text can't end it."""
    return "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)


def console(step: Step) -> str:
    return "\n".join(f"$ {c.typed}" + (f"\n{c.output.rstrip()}" if c.output.strip() else "") for c in step.commands)


def markdown(steps: list[Step]) -> str:
    out = ["# A walkthrough on a tiny project", "", "Generated by `scripts/walkthrough.py`. Don't edit by hand.", "",
           f"![{ALT}](walkthrough.gif)", "",
           "New to docs-proof? Here it is on a tiny made-up project, one step at a time. The script makes the project "
           "in a temporary folder and runs every command shown, so all the output here and in the GIF above is from a "
           "real run (`docs-proof` runs as `python -P -m docsproof`, the same program).", ""]
    for number, step in enumerate(steps, 1):
        text = console(step)
        out += [f"## {number}. {step.title}", "", step.caption, "", f"{fence(text)}console", text, fence(text), ""]
        if step.notes:
            out += [f"- {n.text}" for n in step.notes] + [""]
    out += ["## Three ways to use it", "", *[f"- **{way}:** {text}" for way, text in WAYS], "",
            "How well it works, measured on real open-source projects, is in [the README](../README.md).", ""]
    return "\n".join(out)


def digest(page: str) -> str:
    return hashlib.sha256(page.encode("utf-8")).hexdigest()


# Drawing the GIF. The terminal is a fixed grid, and every step must fit on one screen.
W, H = 1280, 830
COLS, ROWS, MONO = 96, 20, 20  # MONO: the terminal's font size; Menlo is then 12 pixels a character
MARGIN, PAD, PAD_TOP, BAR, LINE = 36, 20, 14, 36, 29
TOP = 164  # where the terminal window starts, under the caption
COLORS = {"page": "#0d1117", "window": "#161b22", "bar": "#21262d", "edge": "#30363d", "text": "#e6edf3",
          "dim": "#5b636e", "band": "#1a2a3f", "accent": "#58a6ff", "title": "#f0f6fc", "caption": "#c9d1d9",
          "code": "#79c0ff", "muted": "#8b949e", "prompt": "#7ee787", "red": "#ff7b72", "green": "#7ee787",
          "cyan": "#56d4dd"}
FONTS = {  # (path, index in the collection) for regular and bold: macOS first, then the usual Linux paths
    "mono": [(("/System/Library/Fonts/Menlo.ttc", 0), ("/System/Library/Fonts/Menlo.ttc", 1)),
             (("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0))],
    "sans": [(("/System/Library/Fonts/HelveticaNeue.ttc", 0), ("/System/Library/Fonts/HelveticaNeue.ttc", 1)),
             (("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0))],
}
TYPE_MS, BEFORE_MS, AFTER_MS, BETWEEN_MS = 55, 600, 400, 700  # typing a key, and the pauses around a command


def reading_ms(text: str) -> int:
    """Time to read a caption: about four words a second, plus a moment to look at the screen."""
    return 1000 + 250 * len(text.split())


@functools.cache
def font(family: str, size: int, bold: bool = False):
    from PIL import ImageFont
    for pair in FONTS[family]:
        path, index = pair[bold]
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=index)
    raise SystemExit(f"walkthrough: no {family} font found; tried {[p[bold][0] for p in FONTS[family]]}")


def wrap(text: str, cols: int) -> list[str]:
    """A terminal line, wrapped at the last space that fits (or at the edge, when there's none). The rows after
    the first start under the line's text: past its indent, and past a why: or fix: label."""
    head = len(text) - len(text.lstrip(" ")) + (5 if text.lstrip(" ").startswith(("why: ", "fix: ")) else 0)
    head = min(head, cols // 2)
    out, row = [], text
    while len(row) > cols:
        indent = len(row) - len(row.lstrip(" "))
        cut = row.rfind(" ", 0, cols + 1)
        cut, rest = (cols, row[cols:]) if cut <= indent else (cut, row[cut + 1:])
        out.append(row[:cut])
        row = " " * head + rest
    return [*out, row]


def diff_colors(line: str) -> list[tuple[str, str, bool]]:
    """A line of git diff in the colors git uses in a terminal."""
    if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
        return [(line, "text", True)]
    if line.startswith("@@"):
        end = line.find("@@", 2) + 2
        return [(line[:end], "cyan", False), (line[end:], "text", False)]
    if line.startswith("-"):
        return [(line, "red", False)]
    if line.startswith("+"):
        return [(line, "green", False)]
    return [(line, "text", False)]


def screen(step: Step) -> tuple[list[list[tuple[str, str, bool]]], list[int], dict[int, list[int]]]:
    """The step's terminal rows, the row each command is typed on, and the rows of each line of its last output."""
    rows, typed_at, last = [], [], {}
    for number, command in enumerate(step.commands):
        typed_at.append(len(rows))
        rows.append([("$ ", "prompt", False), (command.typed, "text", False)])
        for line_no, line in enumerate(command.lines):
            pieces = wrap(line, COLS)
            if number == len(step.commands) - 1:
                last[line_no] = list(range(len(rows), len(rows) + len(pieces)))
            for piece in pieces:
                rows.append(diff_colors(piece) if command.typed == "git diff" else [(piece, "text", False)])
    if len(rows) + 1 > ROWS:
        raise SystemExit(f"walkthrough: step {step.title!r} needs {len(rows) + 1} rows, and the terminal has {ROWS}")
    return rows, typed_at, last


def words(text: str) -> list[list[tuple[str, bool]]]:
    """A caption's words, each a list of (piece, is code), split at the spaces outside `code`."""
    out, word = [], []
    for number, part in enumerate(text.split("`")):
        if number % 2:
            word.append((part, True))
            continue
        for index, chunk in enumerate(part.split(" ")):
            if index and word:
                out.append(word)
                word = []
            if chunk:
                word.append((chunk, False))
    return [*out, word] if word else out


class Painter:
    def __init__(self) -> None:
        from PIL import Image, ImageDraw
        self.Image, self.ImageDraw = Image, ImageDraw
        self.mono, self.mono_bold = font("mono", MONO), font("mono", MONO, bold=True)
        self.advance = self.mono.getlength("0")
        if COLS * self.advance > W - 2 * MARGIN - 2 * PAD:
            raise SystemExit("walkthrough: the terminal's columns don't fit in the window")

    def rich(self, draw, text: str, x: float, y: float, width: float, size: int, color: str, max_lines: int,
             center: bool = False, bold: bool = False) -> float:
        """Draws text with `code` in the monospace font, wrapped to the width. Returns where the next line goes."""
        plain, code = font("sans", size, bold), font("mono", round(size * 0.9))
        space = plain.getlength(" ")
        measure = lambda word: sum((code if is_code else plain).getlength(piece) for piece, is_code in word)
        lines, line, used = [], [], 0.0
        for word in words(text):
            extra = measure(word) + (space if line else 0)
            if line and used + extra > width:
                lines.append((line, used))
                line, used = [], 0.0
                extra = measure(word)
            line.append(word)
            used += extra
        lines.append((line, used))
        if len(lines) > max_lines:
            raise SystemExit(f"walkthrough: {text!r} needs {len(lines)} lines, and has room for {max_lines}")
        step = round(size * 1.3)
        for line, used in lines:
            left = x + (width - used) / 2 if center else x
            for index, word in enumerate(line):
                if index:
                    left += space
                for piece, is_code in word:
                    draw.text((left, y), piece, font=code if is_code else plain,
                              fill=COLORS["code"] if is_code else COLORS[color], anchor="ls")
                    left += (code if is_code else plain).getlength(piece)
            y += step
        return y

    def page(self):
        image = self.Image.new("RGB", (W, H), COLORS["page"])
        return image, self.ImageDraw.Draw(image)

    def title_card(self):
        image, draw = self.page()
        draw.text((W / 2, 355), "docs-proof", font=font("mono", 72, bold=True), fill=COLORS["title"], anchor="ms")
        y = self.rich(draw, TITLE, 140, 435, W - 280, 30, "caption", 2, center=True)
        self.rich(draw, "A walkthrough on a tiny project. Every line of output is from a real run.", 140, y + 26,
                  W - 280, 22, "muted", 1, center=True)
        return image

    def end_card(self):
        image, draw = self.page()
        draw.text((160, 190), "Three ways to use it", font=font("sans", 40, bold=True), fill=COLORS["title"],
                  anchor="ls")
        y = 270
        for way, text in WAYS:
            draw.text((160, y), way, font=font("sans", 28, bold=True), fill=COLORS["accent"], anchor="ls")
            y = self.rich(draw, text[0].upper() + text[1:], 160, y + 40, W - 320, 25, "caption", 2) + 34
        self.rich(draw, "How well it works, measured on real open-source projects, is in the README.", 160, y + 30,
                  W - 320, 22, "muted", 1)
        return image

    def frame(self, number: int, total: int, step: Step, text: str, rows, highlight: set[int] = frozenset(),
              cursor: tuple[int, int] | None = None):
        image, draw = self.page()
        draw.text((MARGIN, 40), f"Step {number} of {total}", font=font("sans", 18), fill=COLORS["accent"], anchor="ls")
        draw.text((MARGIN, 80), step.title, font=font("sans", 30, bold=True), fill=COLORS["title"], anchor="ls")
        self.rich(draw, text, MARGIN, 120, W - 2 * MARGIN, 23, "caption", 2)
        left, right, bottom = MARGIN, W - MARGIN, TOP + BAR + 2 * PAD_TOP + ROWS * LINE
        draw.rounded_rectangle((left, TOP, right, bottom), 12, fill=COLORS["window"])
        draw.rounded_rectangle((left, TOP, right, TOP + BAR), 12, fill=COLORS["bar"], corners=(True, True, False, False))
        draw.line((left, TOP + BAR, right, TOP + BAR), fill=COLORS["edge"])
        draw.rounded_rectangle((left, TOP, right, bottom), 12, outline=COLORS["edge"])
        for index, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            cx, cy = left + 22 + 20 * index, TOP + BAR / 2
            draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=color)
        draw.text((W / 2, TOP + BAR / 2), "tiny", font=font("sans", 15), fill=COLORS["muted"], anchor="mm")
        top = TOP + BAR + PAD_TOP
        for row in highlight:
            draw.rectangle((left + 1, top + row * LINE, right - 1, top + (row + 1) * LINE - 1), fill=COLORS["band"])
            draw.rectangle((left + 1, top + row * LINE, left + 4, top + (row + 1) * LINE - 1), fill=COLORS["accent"])
        for row, pieces in enumerate(rows):
            x = left + PAD
            for piece, color, bold in pieces:
                shade = "dim" if highlight and row not in highlight else color
                draw.text((x, top + row * LINE + 21), piece, font=self.mono_bold if bold else self.mono,
                          fill=COLORS[shade], anchor="ls")
                x += len(piece) * self.advance
        if cursor:
            row, col = cursor
            x = left + PAD + col * self.advance
            draw.rectangle((x, top + row * LINE + 4, x + self.advance - 1, top + row * LINE + 26), fill=COLORS["text"])
        return image


def frames(steps: list[Step]) -> list[tuple[object, int]]:
    """Every frame of the GIF, with how long it shows (milliseconds)."""
    painter = Painter()
    out = [(painter.title_card(), 4000)]
    for number, step in enumerate(steps, 1):
        rows, typed_at, last = screen(step)
        show = lambda upto, cursor, text=step.caption, highlight=frozenset(): painter.frame(
            number, len(steps), step, text, upto, highlight, cursor)
        for index, command in enumerate(step.commands):
            start = typed_at[index]
            shown = rows[:start]
            for count in range(len(command.typed) + 1):
                line = [("$ ", "prompt", False), (command.typed[:count], "text", False)]
                ms = BEFORE_MS if count == 0 else TYPE_MS
                out.append((show(shown + [line], (start, 2 + count)), ms))
            out[-1] = (out[-1][0], AFTER_MS)
            end = typed_at[index + 1] if index + 1 < len(typed_at) else len(rows)
            out.append((show(rows[:end] + [[("$ ", "prompt", False)]], (end, 2)), BETWEEN_MS))
        final = rows + [[("$ ", "prompt", False)]]
        lines_shown = sum(len(c.lines) for c in step.commands)
        out[-1] = (out[-1][0], max(2500, reading_ms(step.caption)) + 80 * lines_shown)
        for item in step.notes:
            highlight = {row for line in item.lines for row in last[line]}
            out.append((show(final, (len(rows), 2), item.text, highlight), reading_ms(item.text) + 400))
    out.append((painter.end_card(), 8000))
    return out


def draw(steps: list[Step], page: str, path: Path = GIF) -> tuple[int, int]:
    """Writes the GIF with one palette for every frame, and the text page's SHA-256 in its comment. Returns the
    number of frames and the total time (milliseconds)."""
    from PIL import Image
    shots = frames(steps)
    merged = []  # a frame that's the same as the one before only adds its time
    for image, ms in shots:
        if merged and merged[-1][0].tobytes() == image.tobytes():
            merged[-1] = (merged[-1][0], merged[-1][1] + ms)
        else:
            merged.append((image, ms))
    keys = [image for image, ms in merged if ms >= 1000]  # every frame that stays a while: all the colors there are
    sheet = Image.new("RGB", (W, H * len(keys)))
    for index, image in enumerate(keys):
        sheet.paste(image, (0, H * index))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    images = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image, _ in merged]
    comment = f"Made by scripts/walkthrough.py from the run on docs/walkthrough.md (sha256 {digest(page)})"
    images[0].save(path, save_all=True, append_images=images[1:], duration=[ms for _, ms in merged], loop=0,
                   optimize=False, comment=comment.encode("ascii"))
    return len(merged), sum(ms for _, ms in merged)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--text", action="store_true", help="write the text page only (no Pillow needed)")
    args = parser.parse_args(argv)
    steps = run()
    page = markdown(steps)
    PAGE.write_text(page, encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)}")
    if not args.text:
        try:
            import PIL  # noqa: F401
        except ImportError:
            raise SystemExit("walkthrough: drawing the GIF needs Pillow: pip install -r requirements-walkthrough.txt "
                             "(or use --text for the page only)") from None
        count, ms = draw(steps, page)
        print(f"wrote {GIF.relative_to(ROOT)}: {count} frames, {ms / 1000:.0f} seconds, "
              f"{GIF.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
