from docsproof.docs import doc_files, is_doc, mentions, qualifiers


def test_doc_files_are_the_readme_and_docs_folder_without_history_or_requirements(tiny):
    assert doc_files(tiny) == ["README.md", "docs/usage.md"]


def test_which_paths_count_as_docs():
    for path in ["README", "README.rst", "CONTRIBUTING.md", "docs/security.md", "docs/guide/cli.rst", "doc/a.txt",
                 "docs/build/index.rst"]:  # alembic keeps its docs' source in docs/build
        assert is_doc(path), path
    for path in ["CHANGELOG.md", "HISTORY.rst", "SECURITY.md", "LICENSE.txt", "requirements.txt",
                 "docs/changelog.md", "docs/releases/1.0.md", "docs/requirements.txt", "docs/release-notes.rst",
                 "src/README.py", "examples/notes.md", "docs/_build/index.md", "build/docs/x.md"]:
        assert not is_doc(path), path


def test_mentions_are_whole_tokens_in_docs_only(tiny):
    found = [(m.file, m.line) for m in mentions(tiny, "--max-results", "option")]
    assert found == [("README.md", 2), ("docs/usage.md", 1)]  # not the changelog
    assert mentions(tiny, "--max", "option") == []  # part of a longer option isn't a mention


def test_another_tools_options_dont_count(tiny):
    assert mentions(tiny, "--upgrade", "option") == []  # "pip install --upgrade tiny" is pip's option


def test_identifier_and_path_mentions(tiny):
    assert [(m.file, m.line) for m in mentions(tiny, "fetch_items", "identifier")] == [("README.md", 5)]
    assert [(m.file, m.line) for m in mentions(tiny, "examples/basic.py", "path")] == [("README.md", 4)]
    assert mentions(tiny, "basic.py", "path") == []  # a path's last part alone isn't the path


def test_qualifiers_name_the_package_in_front_of_a_mention():
    assert qualifiers('"_extensions": ["jinja2_time.TimeExtension"]', "TimeExtension") == ["jinja2_time"]
    assert qualifiers("- ``cookiecutter.extensions.TimeExtension``", "TimeExtension") == ["cookiecutter"]
    assert qualifiers("passed an :class:`.AutogenContext`,", "AutogenContext") == [None]
    assert qualifiers("from uvicorn.workers import UvicornWorker", "UvicornWorker") == [None]
    assert qualifiers("[More info here.](docs/configuration/git_hook.md)", "git_hook") == ["<path>"]


def test_lines_are_split_as_git_splits_them():
    from docsproof.docs import split_lines
    assert split_lines("a\x0cb\nc d\x85e\r\nf\n") == ["a\x0cb", "c d\x85e", "f"]  # only "\n" ends a line
    assert split_lines("") == [] and split_lines("\n") == [""] and split_lines("a") == ["a"]
    assert split_lines("a\rb\n") == ["a\rb"]  # a lone "\r" isn't a line ending for git
    assert "a\x0cb\nc".splitlines() == ["a", "b", "c"]  # what docs-proof used before, and why it drifted


def test_doc_files_leave_out_links_and_names_that_arent_utf8(tmp_path):
    import os
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    (root / "docs" / "usage.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("x\n", encoding="utf-8")
    (root / "docs" / "notes.md").symlink_to(tmp_path / "notes.md")  # out of the folder
    (root / "docs" / "index.md").symlink_to("../README.md")  # in it: README.md is read under its own name
    (root / "doc").symlink_to("docs")  # a folder link: docs/usage.md would be read twice
    (root / "docs" / "gone.md").symlink_to("nowhere.md")
    try:
        (root / "docs" / os.fsdecode(b"caf\xe9.md")).write_text("x\n", encoding="utf-8")
    except OSError:
        pass  # macOS doesn't allow a name that isn't UTF-8; Linux does
    assert doc_files(root) == ["README.md", "docs/usage.md"]


def test_a_repository_reached_through_a_link_still_has_its_docs(tmp_path):
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    (root / "docs" / "usage.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "alias").symlink_to(root)  # as /tmp is a link to /private/tmp on macOS
    assert doc_files(tmp_path / "alias") == doc_files(root) == ["README.md", "docs/usage.md"]
