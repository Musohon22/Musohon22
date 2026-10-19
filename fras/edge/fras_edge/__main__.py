"""python -m fras_edge activate --server URL --code XXXXXXXX | run [--port 8100]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # make the `fras` package importable

from fras.biometrics.providers import DevProvider, OnnxProvider  # noqa: E402

from .agent import Agent, HttpRelay, SimulatedRelay  # noqa: E402
from .store import Store  # noqa: E402
from .transport import Gateway, HttpTransport  # noqa: E402


def build(args) -> Agent:
    data = Path(args.data_dir)
    store = Store(str(data / "edge.db"))
    server = args.server or store.get("server")
    if not server:
        sys.exit("--server is required on first run")
    store.put("server", server)
    if os.environ.get("FRAS_EDGE_PROVIDER", "dev") == "onnx":
        provider = OnnxProvider(os.environ["FRAS_DETECTOR_MODEL"], os.environ["FRAS_RECOGNIZER_MODEL"],
                                os.environ.get("FRAS_PAD_MODEL"))
    else:
        logging.warning("DEV biometric provider in use: NOT a real face recognizer (testing only)")
        provider = DevProvider()
    relay = HttpRelay(os.environ["FRAS_RELAY_URL"]) if os.environ.get("FRAS_RELAY_URL") else SimulatedRelay()
    return Agent(store, Gateway(HttpTransport(server)), provider, relay, data_dir=str(data))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="fras_edge")
    p.add_argument("--data-dir", default=os.environ.get("FRAS_EDGE_DATA", ".edge"))
    p.add_argument("--server")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("activate")
    a.add_argument("--code", required=True)
    a.add_argument("--serial")
    r = sub.add_parser("run")
    r.add_argument("--port", type=int, default=8100)
    args = p.parse_args(argv)
    agent = build(args)
    if args.cmd == "activate":
        info = agent.activate(args.code, args.serial)
        print("activated:", info["device_id"], "site:", (info.get("site") or {}).get("name"))
        return
    if not agent.activated:
        sys.exit("device is not activated: run `activate --code ...` first")
    threading.Thread(target=agent.run_forever, daemon=True).start()
    import uvicorn
    from .server import create_kiosk_app
    uvicorn.run(create_kiosk_app(agent), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
