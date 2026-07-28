# 影 Kageboard

Web dashboard for [Kage](https://github.com/tamnd/kage) — manage, clone, browse, and pack offline website mirrors from your browser.

Kage is a fantastic CLI for freezing websites into offline mirrors. Kageboard gives it a web UI so you can manage your library of mirrors without remembering flags.

## Features

- **Mirror library** — browse all your cloned sites in a grid with page counts and sizes
- **Clone from the browser** — paste a URL, set scope/depth, watch live progress via WebSocket
- **Browse mirrors inline** — view mirrored pages through an iframe with the toolbar stripped
- **Pack to ZIM** — trigger ZIM archive creation from the UI
- **Delete mirrors** — clean up old mirrors with one click
- **htmx + Alpine.js** — lightweight interactivity, no build step, no SPA framework

## Install

```bash
git clone https://github.com/jcrabapple/kageboard.git
cd kageboard
pip install .
```

Requires **kage** on your PATH. Install it first:

```bash
go install github.com/tamnd/kage/cmd/kage@latest
```

## Quick Start

```bash
kageboard --port 5000
# Open http://127.0.0.1:5000
```

Or run directly:

```bash
python3 -m kageboard.cli --port 5000
```

### CLI Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `5000` | Bind port |
| `--debug` | `false` | Flask debug mode |

## How It Works

Kageboard wraps the `kage` CLI — it calls `kage clone`, `kage serve`, `kage pack` as subprocesses and tracks their output. State is on-disk: your mirrors live wherever Kage puts them (`~/data/kage/` by default). Kageboard just reads and manages them.

```
kageboard
├── kageboard/
│   ├── app.py          # Flask routes + WebSocket
│   ├── kage.py         # Kage CLI wrapper (clone, serve, pack, mirror scanning)
│   ├── manager.py      # Job tracking + background threads
│   ├── cli.py          # Entry point
│   └── templates/      # Jinja2 + htmx + Alpine.js
└── tests/
    ├── test_kage.py    # Mirror scanning + CLI wrapper tests
    └── test_app.py     # Flask route tests
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/<id>` | Get job status |
| `POST` | `/api/clone` | Start a clone (body: `{"url": "...", "max_pages": 50, ...}`) |
| `DELETE` | `/api/mirrors/<host>` | Delete a mirror |
| `POST` | `/api/mirrors/<host>/pack` | Pack mirror to ZIM (body: `{"format": "zim"}`) |
| `WS` | `/ws/clone/<id>` | WebSocket for live clone output |

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Roadmap

- [ ] Pack progress tracking (WebSocket like clone)
- [ ] Search across mirrors (full-text on page titles/content)
- [ ] Batch operations (delete multiple, pack multiple)
- [ ] ZIM viewer integration (serve packed archives in-browser)
- [ ] Dark mode
- [ ] Docker image (bundle Kage + Kageboard)

## License

MIT