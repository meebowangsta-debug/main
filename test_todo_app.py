from pathlib import Path

from todo_app import TodoStore


def test_add_list_complete_delete(tmp_path: Path) -> None:
    db = tmp_path / "todos.json"
    store = TodoStore(path=db)

    first = store.add("Buy milk")
    second = store.add("Write code")

    listed = store.list_items()
    assert [item.id for item in listed] == [1, 2]
    assert listed[0].title == "Buy milk"

    done_item = store.complete(first.id)
    assert done_item.done is True

    deleted = store.delete(second.id)
    assert deleted.id == 2

    reloaded = TodoStore(path=db)
    assert len(reloaded.list_items()) == 1
    assert reloaded.list_items()[0].done is True
