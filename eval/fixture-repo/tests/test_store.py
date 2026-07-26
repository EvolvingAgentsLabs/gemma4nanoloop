from todo.store import Store


def test_add_and_pending():
    s = Store()
    s.add("write plan")
    assert len(s.pending()) == 1


def test_complete():
    s = Store()
    s.add("ship it")
    assert s.complete("ship it") is True
    assert s.pending() == []
