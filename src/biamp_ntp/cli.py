"""Command-line interface: ``biamp-ntp``.

Examples::

    biamp-ntp --host 192.168.1.199 devid
    biamp-ntp --host 192.168.1.199 scan OUTLVLPM
    biamp-ntp --host 192.168.1.199 get OUTLVLPM 8 5
    biamp-ntp --host 192.168.1.199 set OUTLVLPM 8 5 -6.0
    biamp-ntp --host 192.168.1.199 raw GET 0 DEVID
"""
import argparse
import sys

from .client import BiampNTP, BiampError
from .scan import scan

__all__ = ["main", "build_parser"]


def _parse_range(s):
    lo, _, hi = s.partition("-")
    return int(lo), int(hi or lo)


def build_parser():
    p = argparse.ArgumentParser(
        prog="biamp-ntp",
        description="Control a Biamp Nexia/Audia DSP over the Text Protocol "
                    "(telnet, port 23, no auth).")
    p.add_argument("--host", required=True, help="DSP IP address or hostname")
    p.add_argument("--device", type=int, default=1,
                   help="device number (default 1; read it with the 'devid' command)")
    p.add_argument("--port", type=int, default=23)
    p.add_argument("--timeout", type=float, default=3.0)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devid", help="read the device number (GET 0 DEVID)")

    sp = sub.add_parser("scan", help="find instance IDs that answer an attribute")
    sp.add_argument("attr", help="attribute code, e.g. OUTLVLPM or MMLVLOUT")
    sp.add_argument("idx", nargs="*", type=int, help="index/channel to probe (default 1)")
    sp.add_argument("--range", default="1-200", help="instance range, e.g. 1-300")

    sp = sub.add_parser("get", help="GET an attribute")
    sp.add_argument("attr")
    sp.add_argument("inst", type=int)
    sp.add_argument("idx", nargs="*", type=int)

    sp = sub.add_parser("set", help="SET an attribute (last arg is the value)")
    sp.add_argument("attr")
    sp.add_argument("inst", type=int)
    sp.add_argument("args", nargs="+", metavar="idx...-value")

    sp = sub.add_parser("raw", help="send a raw command line and print the reply")
    sp.add_argument("line", nargs=argparse.REMAINDER)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    dsp = BiampNTP(args.host, device=args.device, port=args.port, timeout=args.timeout)
    try:
        with dsp:
            if args.cmd == "devid":
                print(dsp.device_id())
            elif args.cmd == "scan":
                lo, hi = _parse_range(args.range)
                idx = args.idx or [1]
                n = 0
                for inst, val in scan(dsp, args.attr, *idx, rng=range(lo, hi + 1)):
                    print("instance %d -> %s" % (inst, val))
                    n += 1
                sys.stdout.flush()
                print("(%d instance(s) answered %s)" % (n, args.attr), file=sys.stderr)
            elif args.cmd == "get":
                print(dsp.get(args.attr, args.inst, *args.idx))
            elif args.cmd == "set":
                idx, value = args.args[:-1], args.args[-1]
                dsp.set(args.attr, args.inst, *[int(i) for i in idx], value)
                print("+OK")
            elif args.cmd == "raw":
                print(dsp.command(" ".join(args.line)))
    except BiampError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("connection error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
