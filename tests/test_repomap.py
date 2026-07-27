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
