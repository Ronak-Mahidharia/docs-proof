"""A tiny repository, written fresh for each test, with the kinds of names docs refer to."""
from pathlib import Path

import pytest

FILES = {
    "README.md": (
        "# tiny\n"
        "Run `tiny --max-results 5` to see five results.\n"
        "Set TINY_TOKEN to log in.\n"
        "See examples/basic.py for an example.\n"
        "Call `fetch_items()` from Python.\n"
        "Use `--limit` to cap the list (default: 10).\n"
        "Requires Python 3.9 or later.\n"
        "pip install --upgrade tiny\n"
    ),
    "CHANGELOG.md": "- Added --max-results\n",
    "docs/usage.md": "Use --max-results to limit output.\nThe --verbose flag prints more.\n",
    "requirements.txt": "requests\n",
    "pyproject.toml": '[project]\nname = "tiny"\nrequires-python = ">=3.9"\n',
    "tiny/__init__.py": "",
    "tiny/cli.py": (
        "import argparse\n"
        "import os\n"
        "\n"
        "\n"
        "def build_parser():\n"
        "    parser = argparse.ArgumentParser()\n"
        '    parser.add_argument("--max-results", type=int, default=20, help="at most N (see --max-results)")\n'
        '    parser.add_argument("--limit", type=int, default=10)\n'
        '    parser.add_argument("-v", "--verbose", action="store_true")\n'
        "    parser.add_argument(\n"
        '        "--upgrade",\n'
        '        action="store_true",  # a comment before the closing parenthesis\n'
        "    )\n"
        "    return parser\n"
        "\n"
        "\n"
        "def main(argv=None):\n"
        "    args = build_parser().parse_args(argv)\n"
        '    token = os.environ.get("TINY_TOKEN")\n'
        "    return args.max_results, args.limit, args.verbose, args.upgrade, token\n"
        "\n"
        "\n"
        "def fetch_items():\n"
        "    return []\n"
        "\n"
        "\n"
        "def _helper():\n"
        "    return 1\n"
    ),
    "tiny/hello.py": (
        "import click\n"
        "\n"
        "\n"
        "@click.command()\n"
        '@click.option("--color/--no-color", default=True)\n'
        '@click.option("--name", "-n", default="x")\n'
        "def hello(color, name):\n"
        "    print(color, name)\n"
    ),
    "tiny/data.py": 'EXAMPLE = "examples/basic.py"\n',
    "examples/basic.py": 'print("hi")\n',
    "tests/test_cli.py": 'import argparse\nargparse.ArgumentParser().add_argument("--test-only")\n',
}


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def tiny(tmp_path: Path) -> Path:
    return write(tmp_path / "tiny-repo", FILES)
