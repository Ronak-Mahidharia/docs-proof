FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
RUN pip install --no-cache-dir uv==0.12.24 && useradd --create-home --uid 10001 sandbox
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 PBR_VERSION=0.0.0 COVERAGE_DISABLE_EXTENSION=1
COPY data/sandbox/pins /pins
COPY --chown=10001:10001 data/repos/asottile__pyupgrade /work/asottile__pyupgrade
RUN uv venv --python /usr/local/bin/python3.14 /envs/asottile__pyupgrade && uv pip install --python /envs/asottile__pyupgrade/bin/python --no-deps -r /pins/asottile__pyupgrade.txt && uv pip install --python /envs/asottile__pyupgrade/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/asottile__pyupgrade"
COPY --chown=10001:10001 data/repos/callowayproject__bump-my-version /work/callowayproject__bump-my-version
RUN uv venv --python /usr/local/bin/python3.14 /envs/callowayproject__bump-my-version && uv pip install --python /envs/callowayproject__bump-my-version/bin/python --no-deps -r /pins/callowayproject__bump-my-version.txt && uv pip install --python /envs/callowayproject__bump-my-version/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/callowayproject__bump-my-version"
COPY --chown=10001:10001 data/repos/cookiecutter__cookiecutter /work/cookiecutter__cookiecutter
RUN uv venv --python /usr/local/bin/python3.14 /envs/cookiecutter__cookiecutter && uv pip install --python /envs/cookiecutter__cookiecutter/bin/python --no-deps -r /pins/cookiecutter__cookiecutter.txt && uv pip install --python /envs/cookiecutter__cookiecutter/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/cookiecutter__cookiecutter"
COPY --chown=10001:10001 data/repos/coveragepy__coveragepy /work/coveragepy__coveragepy
RUN uv venv --python /usr/local/bin/python3.14 /envs/coveragepy__coveragepy && uv pip install --python /envs/coveragepy__coveragepy/bin/python --no-deps -r /pins/coveragepy__coveragepy.txt && uv pip install --python /envs/coveragepy__coveragepy/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/coveragepy__coveragepy"
COPY --chown=10001:10001 data/repos/encode__httpx /work/encode__httpx
RUN uv venv --python /usr/local/bin/python3.14 /envs/encode__httpx && uv pip install --python /envs/encode__httpx/bin/python --no-deps -r /pins/encode__httpx.txt && uv pip install --python /envs/encode__httpx/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/encode__httpx[cli]"
COPY --chown=10001:10001 data/repos/gleitz__howdoi /work/gleitz__howdoi
RUN uv venv --python /usr/local/bin/python3.14 /envs/gleitz__howdoi && uv pip install --python /envs/gleitz__howdoi/bin/python --no-deps -r /pins/gleitz__howdoi.txt && uv pip install --python /envs/gleitz__howdoi/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/gleitz__howdoi"
COPY --chown=10001:10001 data/repos/hhatto__autopep8 /work/hhatto__autopep8
RUN uv venv --python /usr/local/bin/python3.14 /envs/hhatto__autopep8 && uv pip install --python /envs/hhatto__autopep8/bin/python --no-deps -r /pins/hhatto__autopep8.txt && uv pip install --python /envs/hhatto__autopep8/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/hhatto__autopep8"
COPY --chown=10001:10001 data/repos/jazzband__pip-tools /work/jazzband__pip-tools
RUN uv venv --python /usr/local/bin/python3.14 /envs/jazzband__pip-tools && uv pip install --python /envs/jazzband__pip-tools/bin/python --no-deps -r /pins/jazzband__pip-tools.txt && uv pip install --python /envs/jazzband__pip-tools/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/jazzband__pip-tools"
COPY --chown=10001:10001 data/repos/Kludex__uvicorn /work/Kludex__uvicorn
RUN uv venv --python /usr/local/bin/python3.14 /envs/Kludex__uvicorn && uv pip install --python /envs/Kludex__uvicorn/bin/python --no-deps -r /pins/Kludex__uvicorn.txt && uv pip install --python /envs/Kludex__uvicorn/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/Kludex__uvicorn"
COPY --chown=10001:10001 data/repos/mkdocs__mkdocs /work/mkdocs__mkdocs
RUN uv venv --python /usr/local/bin/python3.14 /envs/mkdocs__mkdocs && uv pip install --python /envs/mkdocs__mkdocs/bin/python --no-deps -r /pins/mkdocs__mkdocs.txt && uv pip install --python /envs/mkdocs__mkdocs/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/mkdocs__mkdocs"
COPY --chown=10001:10001 data/repos/pallets__flask /work/pallets__flask
RUN uv venv --python /usr/local/bin/python3.14 /envs/pallets__flask && uv pip install --python /envs/pallets__flask/bin/python --no-deps -r /pins/pallets__flask.txt && uv pip install --python /envs/pallets__flask/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/pallets__flask"
COPY --chown=10001:10001 data/repos/psf__black /work/psf__black
RUN uv venv --python /usr/local/bin/python3.14 /envs/psf__black && uv pip install --python /envs/psf__black/bin/python --no-deps -r /pins/psf__black.txt && uv pip install --python /envs/psf__black/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/psf__black[d]"
COPY --chown=10001:10001 data/repos/PyCQA__bandit /work/PyCQA__bandit
RUN uv venv --python /usr/local/bin/python3.14 /envs/PyCQA__bandit && uv pip install --python /envs/PyCQA__bandit/bin/python --no-deps -r /pins/PyCQA__bandit.txt && uv pip install --python /envs/PyCQA__bandit/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/PyCQA__bandit"
COPY --chown=10001:10001 data/repos/PyCQA__isort /work/PyCQA__isort
RUN uv venv --python /usr/local/bin/python3.14 /envs/PyCQA__isort && uv pip install --python /envs/PyCQA__isort/bin/python --no-deps -r /pins/PyCQA__isort.txt && uv pip install --python /envs/PyCQA__isort/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/PyCQA__isort"
COPY --chown=10001:10001 data/repos/pypa__hatch /work/pypa__hatch
RUN uv venv --python /usr/local/bin/python3.14 /envs/pypa__hatch && uv pip install --python /envs/pypa__hatch/bin/python --no-deps -r /pins/pypa__hatch.txt && uv pip install --python /envs/pypa__hatch/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/pypa__hatch"
COPY --chown=10001:10001 data/repos/pypa__pipx /work/pypa__pipx
RUN uv venv --python /usr/local/bin/python3.14 /envs/pypa__pipx && uv pip install --python /envs/pypa__pipx/bin/python --no-deps -r /pins/pypa__pipx.txt && uv pip install --python /envs/pypa__pipx/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/pypa__pipx"
COPY --chown=10001:10001 data/repos/pypa__twine /work/pypa__twine
RUN uv venv --python /usr/local/bin/python3.14 /envs/pypa__twine && uv pip install --python /envs/pypa__twine/bin/python --no-deps -r /pins/pypa__twine.txt && uv pip install --python /envs/pypa__twine/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/pypa__twine"
COPY --chown=10001:10001 data/repos/simonw__datasette /work/simonw__datasette
RUN uv venv --python /usr/local/bin/python3.14 /envs/simonw__datasette && uv pip install --python /envs/simonw__datasette/bin/python --no-deps -r /pins/simonw__datasette.txt && uv pip install --python /envs/simonw__datasette/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/simonw__datasette"
COPY --chown=10001:10001 data/repos/simonw__llm /work/simonw__llm
RUN uv venv --python /usr/local/bin/python3.14 /envs/simonw__llm && uv pip install --python /envs/simonw__llm/bin/python --no-deps -r /pins/simonw__llm.txt && uv pip install --python /envs/simonw__llm/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/simonw__llm"
COPY --chown=10001:10001 data/repos/simonw__shot-scraper /work/simonw__shot-scraper
RUN uv venv --python /usr/local/bin/python3.14 /envs/simonw__shot-scraper && uv pip install --python /envs/simonw__shot-scraper/bin/python --no-deps -r /pins/simonw__shot-scraper.txt && uv pip install --python /envs/simonw__shot-scraper/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/simonw__shot-scraper"
COPY --chown=10001:10001 data/repos/simonw__sqlite-utils /work/simonw__sqlite-utils
RUN uv venv --python /usr/local/bin/python3.14 /envs/simonw__sqlite-utils && uv pip install --python /envs/simonw__sqlite-utils/bin/python --no-deps -r /pins/simonw__sqlite-utils.txt && uv pip install --python /envs/simonw__sqlite-utils/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/simonw__sqlite-utils"
COPY --chown=10001:10001 data/repos/sqlalchemy__alembic /work/sqlalchemy__alembic
RUN uv venv --python /usr/local/bin/python3.14 /envs/sqlalchemy__alembic && uv pip install --python /envs/sqlalchemy__alembic/bin/python --no-deps -r /pins/sqlalchemy__alembic.txt && uv pip install --python /envs/sqlalchemy__alembic/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/sqlalchemy__alembic"
COPY --chown=10001:10001 data/repos/sqlfluff__sqlfluff /work/sqlfluff__sqlfluff
RUN uv venv --python /usr/local/bin/python3.14 /envs/sqlfluff__sqlfluff && uv pip install --python /envs/sqlfluff__sqlfluff/bin/python --no-deps -r /pins/sqlfluff__sqlfluff.txt && uv pip install --python /envs/sqlfluff__sqlfluff/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/sqlfluff__sqlfluff"
COPY --chown=10001:10001 data/repos/theskumar__python-dotenv /work/theskumar__python-dotenv
RUN uv venv --python /usr/local/bin/python3.14 /envs/theskumar__python-dotenv && uv pip install --python /envs/theskumar__python-dotenv/bin/python --no-deps -r /pins/theskumar__python-dotenv.txt && uv pip install --python /envs/theskumar__python-dotenv/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/theskumar__python-dotenv[cli]"
COPY --chown=10001:10001 data/repos/tldr-pages__tldr-python-client /work/tldr-pages__tldr-python-client
RUN uv venv --python /usr/local/bin/python3.14 /envs/tldr-pages__tldr-python-client && uv pip install --python /envs/tldr-pages__tldr-python-client/bin/python --no-deps -r /pins/tldr-pages__tldr-python-client.txt && uv pip install --python /envs/tldr-pages__tldr-python-client/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/tldr-pages__tldr-python-client"
COPY --chown=10001:10001 data/repos/yt-dlp__yt-dlp /work/yt-dlp__yt-dlp
RUN uv venv --python /usr/local/bin/python3.14 /envs/yt-dlp__yt-dlp && uv pip install --python /envs/yt-dlp__yt-dlp/bin/python --no-deps -r /pins/yt-dlp__yt-dlp.txt && uv pip install --python /envs/yt-dlp__yt-dlp/bin/python --exclude-newer 2026-10-10 --no-deps -e "/work/yt-dlp__yt-dlp"
COPY src/docsproof /opt/docsproof/docsproof
USER sandbox
WORKDIR /work
