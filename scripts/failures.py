"""How a script stops when something it needs from outside docs-proof isn't there: git, Docker, or Ollama. It
says what was missing in one line, instead of a traceback. Each script writes its results only after its work is
done, so a stop like this leaves the kept results as they were.
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.error
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from docsproof.model import OLLAMA  # noqa: E402

KEPT = "The kept results weren't changed."
# what the docker command says when Docker isn't running, in older and newer wordings
DOCKER_DOWN = re.compile(r"cannot connect to the docker daemon|failed to connect to the docker api", re.I)
TOOLS = {"git": "git", "docker": "Docker, which the sandbox runs need,"}


def explained(main: Callable[[], None]) -> None:
    """Run a script's main(), and turn a missing tool or service into one line that says what to do."""
    script = Path(sys.argv[0]).name
    try:
        main()
    except FileNotFoundError as error:
        if error.filename not in TOOLS:
            raise
        sys.exit(f"{script}: {TOOLS[error.filename]} isn't installed, or isn't on PATH. {KEPT}")
    except urllib.error.HTTPError as error:
        sys.exit(f"{script}: Ollama answered {error.code} ({error.reason}); a model that isn't there can be pulled "
                 f"with ollama pull. {KEPT}")
    except urllib.error.URLError as error:
        sys.exit(f"{script}: couldn't reach Ollama at {OLLAMA} ({error.reason}); start it with ollama serve. {KEPT}")
    except subprocess.CalledProcessError as error:
        if error.cmd[0] != "docker":
            raise
        sys.exit(f"{script}: {' '.join(error.cmd[:2])} stopped (exit status {error.returncode}); Docker's message is "
                 f"above. {KEPT}")
    except RuntimeError as error:
        if not DOCKER_DOWN.search(str(error)):
            raise
        sys.exit(f"{script}: Docker isn't running; start it, and run this again. {KEPT}")
