"""Run a local float seller + the WebSocket gateway together, so you can try
web/index.html without setting up two processes by hand.

    cd <repo> && PYTHONPATH=. python web/demo_seller.py
    # float 'echo' seller on 127.0.0.1:9000, gateway on 127.0.0.1:8800
    # then open web/index.html and press Buy (defaults already point here).
"""

import asyncio

from p2pcp import daemon as D, worker as WK, gateway as GW


def echo(job, index):                                  # a trivial float worker
    return b"answer: " + job


def main():
    seller = D.Daemon(
        D.L.Identity.from_seed(b"demo-seller".ljust(32, b"0")),
        worker=WK.FunctionWorker(echo, vclass=WK.VCLASS_FLOAT))
    h, p = seller.start("127.0.0.1", 9000)
    print(f"[demo] float echo seller on {h}:{p}", flush=True)
    try:
        asyncio.run(GW.serve("127.0.0.1", 8800))
    except KeyboardInterrupt:
        seller.stop()


if __name__ == "__main__":
    main()
