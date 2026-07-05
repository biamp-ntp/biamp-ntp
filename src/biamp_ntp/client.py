"""A small, dependency-free client for the Biamp Nexia / Audia Text Protocol.

The Nexia (CS/PM/SP/VC/TC) and Audia (FLOW, ...) families expose a line-based
control protocol over TCP port 23 (telnet, no authentication). This module
speaks it with nothing but the Python standard library.
"""
import socket
import threading
import time

__all__ = ["BiampNTP", "BiampError"]


class BiampError(Exception):
    """A command returned a protocol error (-ERR:...) or an unparseable reply."""


def _strip_iac(b):
    """Remove telnet IAC negotiation triples (0xFF cmd opt) from a raw buffer.

    The Nexia/Audia telnet server emits IAC negotiation on connect and can
    interleave it with replies; left in, it corrupts parsing.
    """
    out = bytearray()
    i, n = 0, len(b)
    while i < n:
        if b[i] == 0xFF:
            i += 3            # skip IAC + command byte + option byte
            continue
        out.append(b[i])
        i += 1
    return bytes(out)


def _fmt(v):
    """Format a Python value for the wire (bool -> 0/1, tidy floats)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        s = ("%.4f" % v).rstrip("0").rstrip(".")
        return s or "0"
    return str(v)


class BiampNTP:
    """Telnet client for one Biamp DSP.

    Typical use::

        from biamp_ntp import BiampNTP, protocol as p

        with BiampNTP("192.168.1.199") as dsp:
            print(dsp.device_id())                      # device number
            db = dsp.get_float(p.OUTPUT_LEVEL_PM, 8, 5) # output block inst 8, ch 5
            dsp.set(p.OUTPUT_LEVEL_PM, 8, 5, -6.0)      # set ch 5 to -6 dB

    Command grammar::

        GET <dev> <ATTR> <inst> <idx...>           -> value
        SET <dev> <ATTR> <inst> <idx...> <value>   -> +OK
        errors: -ERR:SYNTAX | -ERR:XACTION ERROR

    Instance IDs are assigned at compile time and RENUMBER whenever the design
    is recompiled and re-pushed, so numbers taken from a .nex file go stale.
    Discover them live with :func:`biamp_ntp.scan.scan`.

    ``command()`` is thread-safe (serialized on an internal lock); the telnet
    server is happiest with one client at a time.
    """

    def __init__(self, host, device=1, port=23, timeout=3.0, settle=0.25):
        self.host = host
        self.device = device
        self.port = port
        self.timeout = timeout
        self.settle = settle
        self._sock = None
        self._lock = threading.Lock()

    # -- connection ------------------------------------------------------

    def connect(self):
        """Open the telnet session (idempotent). Returns self."""
        if self._sock is None:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout)
            self._drain()     # swallow banner + IAC negotiation
        return self

    def close(self):
        """Close the session if open."""
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- framing ---------------------------------------------------------

    def _drain(self):
        """Read the whole reply frame: settle briefly, then mop up non-blocking.

        The device dribbles its reply just after echoing the command, so a
        single immediate recv() catches a partial frame (and splits IAC
        triples). A short settle plus a brief non-blocking drain gets it whole.
        """
        time.sleep(self.settle)
        chunks = bytearray()
        self._sock.settimeout(0.15)
        while True:
            try:
                b = self._sock.recv(4096)
                if not b:
                    break
                chunks += b
            except socket.timeout:
                break
        return bytes(chunks)

    def _reply(self, raw):
        """Extract the reply string: strip IAC, take the last non-empty line."""
        lines = [l for l in _strip_iac(raw).replace(b"\r", b"").split(b"\n")
                 if l.strip()]
        return lines[-1].decode("latin-1", "replace").strip() if lines else ""

    # -- I/O -------------------------------------------------------------

    def command(self, text, retry=True):
        """Send one command line; return its reply string. Thread-safe.

        Reconnects and retries once if the socket has dropped (including a
        silent drop that yields an empty reply).
        """
        with self._lock:
            last = ""
            for attempt in (1, 2):
                try:
                    self.connect()
                    self._sock.settimeout(self.timeout)
                    self._sock.sendall((text + "\n").encode())
                    last = self._reply(self._drain())
                    if last or not retry:
                        return last
                    self.close()          # empty reply -> likely dropped; retry
                except OSError:
                    self.close()
                    if attempt == 2 or not retry:
                        raise
            return last

    # -- typed helpers ---------------------------------------------------

    def query(self, attr, inst, *idx):
        """Raw GET: returns the reply string (a value, or -ERR:... on failure)."""
        parts = ["GET", str(self.device), attr, str(inst)]
        parts += [str(i) for i in idx]
        return self.command(" ".join(parts))

    def get(self, attr, inst, *idx):
        """GET, raising BiampError on error/empty; returns the string value."""
        r = self.query(attr, inst, *idx)
        if not r or r.startswith("-ERR"):
            raise BiampError("GET %s %s %s -> %r" % (attr, inst, list(idx), r))
        return r

    def get_float(self, attr, inst, *idx):
        return float(self.get(attr, inst, *idx))

    def get_bool(self, attr, inst, *idx):
        return self.get(attr, inst, *idx).strip() == "1"

    def set(self, attr, inst, *idx_and_value):
        """SET: the last positional is the value, the rest are indices.

        Returns True on +OK, else raises BiampError. Booleans map to 0/1.
        """
        if not idx_and_value:
            raise TypeError("set() needs at least a value")
        idx = idx_and_value[:-1]
        value = idx_and_value[-1]
        parts = ["SET", str(self.device), attr, str(inst)]
        parts += [str(i) for i in idx] + [_fmt(value)]
        r = self.command(" ".join(parts))
        if r != "+OK":
            raise BiampError("SET %s %s %s %s -> %r"
                             % (attr, inst, list(idx), value, r))
        return True

    def device_id(self):
        """Read the device number (GET 0 DEVID)."""
        r = self.command("GET 0 DEVID")
        if not r or r.startswith("-ERR"):
            raise BiampError("GET 0 DEVID -> %r" % r)
        return int(r)
