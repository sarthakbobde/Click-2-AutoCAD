"""Start the Click2CAD web UI.

    .venv311\\Scripts\\python.exe serve.py            # opens http://127.0.0.1:8001
    .venv311\\Scripts\\python.exe serve.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Click2CAD web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)  # V2 uses 8000, so both can run
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"Click2CAD is running at {url}  (Ctrl+C to stop)")
    uvicorn.run("click2cad.server:app", host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
