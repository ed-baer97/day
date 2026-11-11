# AGENTS.md

## Cursor Cloud specific instructions

This repository is a single, self-contained static web page (`index.html`) plus image assets in `images/`. There is no package manager, no build system, no dependencies, and no automated tests or linters.

### Services

- Static site — the entire product is `index.html` (inline CSS + vanilla JS) and the `images/` folder. Core functionality is fully client-side: the date tabs switch entries via the `openDay()` JS function, and the orange buttons trigger `alert()` popups.

### Running

- Serve from the repo root so the relative `images/...` paths resolve over HTTP:
  - `python3 -m http.server 8000` (Python 3 and Node 22 are both preinstalled), then open `http://localhost:8000/`.
- The page also works when opened directly as a `file://` URL, but serving over HTTP more closely matches a real host.

### Lint / test / build

- None exist. There is nothing to install, lint, test, or build. Do not add these unless explicitly requested.
