# Simple Todo App (Python CLI + Web)

A beginner-friendly todo app that uses only Python standard library.

- Works in terminal (CLI) on macOS/Linux/Windows
- Can also run in your browser as a tiny web app
- Stores data in a local `todos.json` file

## Requirements

- Python 3.10+

## Quick start

```bash
python todo_app.py add "Buy milk"
python todo_app.py list
python todo_app.py done 1
python todo_app.py delete 1
```

## Run in browser

```bash
python todo_app.py web --host 127.0.0.1 --port 8000
```

Then open: <http://127.0.0.1:8000>

## Optional: custom data file

```bash
python todo_app.py --db mytodos.json add "Learn GitHub"
python todo_app.py --db mytodos.json list
```

## Run tests

If you have `pytest` installed:

```bash
pytest -q
```

If not, install it once:

```bash
python -m pip install pytest
```
