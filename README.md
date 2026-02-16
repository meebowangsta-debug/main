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


## Financial analysis AI agent helper

This repo also includes `financial_agent.py` for building a daily, high-signal research brief across:
- AI software, AI hardware, AI infrastructure
- Space exploration
- Critical minerals and rare earth elements
- Robotics

Print the bootstrap workflow, source priorities (`x.com` + major financial outlets), and company watchlists:

```bash
python financial_agent.py bootstrap
```

Analyze a JSON file of observations:

```bash
python financial_agent.py analyze --input observations.json
```

Example `observations.json`:

```json
[
  {
    "topic": "AI hardware",
    "company": "NVIDIA",
    "source": "Reuters",
    "url": "https://www.reuters.com/...",
    "summary": "NVIDIA beats earnings and raises guidance after long-term contract win."
  }
]
```
