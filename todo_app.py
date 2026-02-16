#!/usr/bin/env python3
"""Simple Todo app with CLI and browser modes (standard library only)."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs


DEFAULT_DB_PATH = Path("todos.json")


@dataclass
class TodoItem:
    id: int
    title: str
    done: bool = False


class TodoStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.items: list[TodoItem] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.items = [TodoItem(**row) for row in raw]

    def save(self) -> None:
        payload = [asdict(item) for item in self.items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _next_id(self) -> int:
        return max((item.id for item in self.items), default=0) + 1

    def add(self, title: str) -> TodoItem:
        title = title.strip()
        if not title:
            raise ValueError("Todo title cannot be empty.")

        item = TodoItem(id=self._next_id(), title=title)
        self.items.append(item)
        self.save()
        return item

    def list_items(self) -> list[TodoItem]:
        return sorted(self.items, key=lambda item: item.id)

    def get(self, item_id: int) -> TodoItem | None:
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def complete(self, item_id: int) -> TodoItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"No todo found with ID {item_id}.")

        item.done = True
        self.save()
        return item

    def delete(self, item_id: int) -> TodoItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError(f"No todo found with ID {item_id}.")

        self.items = [todo for todo in self.items if todo.id != item_id]
        self.save()
        return item


class TodoRequestHandler(BaseHTTPRequestHandler):
    store: TodoStore

    def do_GET(self) -> None:  # noqa: N802 - method name required by BaseHTTPRequestHandler
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._render_home()

    def do_POST(self) -> None:  # noqa: N802 - method name required by BaseHTTPRequestHandler
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(body)

        try:
            if self.path == "/add":
                self.store.add(form.get("title", [""])[0])
            elif self.path == "/complete":
                self.store.complete(int(form.get("id", ["0"])[0]))
            elif self.path == "/delete":
                self.store.delete(int(form.get("id", ["0"])[0]))
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
        except (ValueError, KeyError):
            pass

        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _render_home(self) -> None:
        items = self.store.list_items()
        rows = "\n".join(_render_item(item) for item in items) or "<p>No todos yet.</p>"
        html = f"""<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Todo CLI + Web</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; }}
      h1 {{ margin-bottom: 0.5rem; }}
      .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
      .row {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid #eee; padding: 0.75rem 0; }}
      .row:first-child {{ border-top: none; }}
      .done {{ color: #777; text-decoration: line-through; }}
      input[type=text] {{ width: 100%; max-width: 460px; padding: 0.5rem; }}
      button {{ padding: 0.4rem 0.6rem; cursor: pointer; }}
      form.inline {{ display: inline; }}
    </style>
  </head>
  <body>
    <h1>Todo App</h1>
    <p>Use this in your browser, or run commands in terminal.</p>
    <div class=\"card\">
      <form method=\"post\" action=\"/add\">
        <input type=\"text\" name=\"title\" placeholder=\"What do you need to do?\" required />
        <button type=\"submit\">Add</button>
      </form>
    </div>
    <div class=\"card\">
      {rows}
    </div>
  </body>
</html>
"""
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _render_item(item: TodoItem) -> str:
    label_class = "done" if item.done else ""
    complete_button = (
        "" if item.done else f"""
        <form method=\"post\" action=\"/complete\" class=\"inline\">
          <input type=\"hidden\" name=\"id\" value=\"{item.id}\" />
          <button type=\"submit\">Done</button>
        </form>
        """
    )

    return f"""
    <div class=\"row\">
      <div><strong>#{item.id}</strong> <span class=\"{label_class}\">{item.title}</span></div>
      <div>
        {complete_button}
        <form method=\"post\" action=\"/delete\" class=\"inline\">
          <input type=\"hidden\" name=\"id\" value=\"{item.id}\" />
          <button type=\"submit\">Delete</button>
        </form>
      </div>
    </div>
    """


def print_items(items: Iterable[TodoItem]) -> None:
    rows = list(items)
    if not rows:
        print("No todos yet. Add one with: python todo_app.py add \"Buy milk\"")
        return

    print("\nTodos")
    print("-----")
    for item in rows:
        status = "[x]" if item.done else "[ ]"
        print(f"{item.id:>3}. {status} {item.title}")


def run_cli(args: argparse.Namespace) -> None:
    store = TodoStore(path=Path(args.db))

    if args.command == "add":
        item = store.add(args.title)
        print(f"Added todo #{item.id}: {item.title}")
    elif args.command == "list":
        print_items(store.list_items())
    elif args.command == "done":
        item = store.complete(args.id)
        print(f"Marked todo #{item.id} as done.")
    elif args.command == "delete":
        item = store.delete(args.id)
        print(f"Deleted todo #{item.id}: {item.title}")
    elif args.command == "web":
        TodoRequestHandler.store = store
        server = ThreadingHTTPServer((args.host, args.port), TodoRequestHandler)
        print(f"Todo web app running at http://{args.host}:{args.port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...")
        finally:
            server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple Todo CLI + browser app")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to JSON database file")

    sub = parser.add_subparsers(dest="command", required=True)

    add_parser = sub.add_parser("add", help="Add a new todo")
    add_parser.add_argument("title", help="Todo title")

    sub.add_parser("list", help="List todos")

    done_parser = sub.add_parser("done", help="Mark a todo as complete")
    done_parser.add_argument("id", type=int, help="Todo ID")

    delete_parser = sub.add_parser("delete", help="Delete a todo")
    delete_parser.add_argument("id", type=int, help="Todo ID")

    web_parser = sub.add_parser("web", help="Run a tiny web UI")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    web_parser.add_argument("--port", type=int, default=8000, help="Port")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_cli(args)


if __name__ == "__main__":
    main()
