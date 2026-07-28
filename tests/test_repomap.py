"""Repo map must let the planner route a symbol to its file."""

from nanoloop import repomap


def test_map_names_defined_symbols(tmp_path):
    """Found by the first multi-step run: without this the planner sent an edit
    to `Item` at todo/__init__.py, which contains only a docstring."""
    (tmp_path / "store.py").write_text(
        '"""Store."""\n\n\nclass Item:\n    pass\n\n\ndef helper():\n    pass\n'
    )
    (tmp_path / "__init__.py").write_text('"""Package."""\n')
    out = repomap.build(tmp_path)
    assert "defines: Item, helper" in out
    # The empty package file must NOT claim to define anything.
    init_line = [ln for ln in out.splitlines() if ln.startswith("__init__.py")][0]
    assert "defines" not in init_line


def test_map_omits_bodies(tmp_path):
    (tmp_path / "m.py").write_text("def f():\n    SECRET_BODY = 1\n    return SECRET_BODY\n")
    assert "SECRET_BODY" not in repomap.build(tmp_path)


def test_symbols_are_top_level_only(tmp_path):
    (tmp_path / "m.py").write_text("class A:\n    def method(self):\n        pass\n")
    out = repomap.build(tmp_path)
    assert "defines: A" in out and "method" not in out


def test_symbol_list_is_capped(tmp_path):
    (tmp_path / "big.py").write_text("".join(f"def f{i}():\n    pass\n\n\n" for i in range(30)))
    assert "..." in repomap.build(tmp_path)


def test_syntax_error_does_not_break_the_map(tmp_path):
    (tmp_path / "broken.py").write_text("def (((:\n")
    assert "broken.py" in repomap.build(tmp_path)


def test_skipped_directories_are_never_walked(tmp_path):
    """`rglob("*")` enumerated and sorted the whole tree before dropping
    SKIP_DIRS, so a repo with a virtualenv paid for every file in it on every
    planning round. Pruning has to happen during the walk, not after."""
    (tmp_path / "keep.py").write_text("A = 1\n")
    for skipped in (".venv", "node_modules", "__pycache__"):
        deep = tmp_path / skipped / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "buried.py").write_text("B = 1\n")

    found = repomap._files(tmp_path)
    assert [p.name for p in found] == ["keep.py"]
    assert "buried" not in repomap.build(tmp_path)


def test_a_file_is_read_once_per_map(tmp_path, monkeypatch):
    """The docstring and the symbol list came from two separate read+parse
    passes over the same file."""
    (tmp_path / "m.py").write_text('"""doc."""\n\n\ndef f():\n    pass\n')
    reads = []
    original = repomap.Path.read_text

    def counting(self, *a, **kw):
        reads.append(str(self))
        return original(self, *a, **kw)

    monkeypatch.setattr(repomap.Path, "read_text", counting)
    out = repomap.build(tmp_path)
    assert "doc." in out and "defines: f" in out
    assert len([r for r in reads if r.endswith("m.py")]) == 1
