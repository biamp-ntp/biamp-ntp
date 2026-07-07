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
    """Remove telnet IAC sequences from a raw buffer.

    Handles the full grammar, not just 3-byte triples:

    - ``IAC IAC``            -> escaped literal 0xFF data byte (kept)
    - ``IAC SB ... IAC SE``  -> subnegotiation block (skipped whole)
    - ``IAC WILL/WONT/DO/DONT <opt>`` -> 3-byte triple (skipped)
    - ``IAC <cmd>``          -> other 2-byte command, e.g. NOP/GA (skipped)

    A sequence left incomplete at the tail stops processing there; callers
    re-strip the whole buffer after every recv(), so it completes on the
    next pass instead of being miscounted.
    """
    out = bytearray()
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c != 0xFF:
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            break                       # partial IAC at tail; wait for more
        cmd = b[i + 1]
        if cmd == 0xFF:                 # IAC IAC -> literal 0xFF
            out.append(0xFF)
            i += 2
        elif cmd == 0xFA:               # SB ... IAC SE
            j = b.find(b"\xff\xf0", i + 2)
            if j < 0:
                break                   # incomplete subnegotiation; wait
            i = j + 2
        elif 0xFB <= cmd <= 0xFE:       # WILL/WONT/DO/DONT <option>
            if i + 2 >= n:
                break                   # partial triple; wait
            i += 3
        else:                           # 2-byte command (NOP, GA, ...)
            i += 2
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

    def __init__(self, host, device=1, port=23, timeout=3.0, settle=0.25,
                 pace=0.05):
        self.host = host
        self.device = device
        self.port = port
        self.timeout = timeout
        self.settle = settle
        # Minimum gap between commands on one connection. The device chokes on
        # full-rate pipelining: it emits an extra "-ERR:# 0x16" line per
        # command and falls progressively behind (observed on a Nexia PM).
        # 50 ms keeps it comfortably below that threshold; set pace=0 at your
        # own risk on firmware you've verified.
        self.pace = pace
        self._sock = None
        self._next_send = 0.0
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
                self._next_send = 0.0  # fresh connection re-drains the banner anyway

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- framing ---------------------------------------------------------

    def _drain(self):
        """Swallow the connect banner + IAC negotiation (connect time only).

        Settle briefly, then read non-blocking until quiet. Only used once
        per connection, so the small fixed cost doesn't affect command rate.
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

    @staticmethod
    def _complete_lines(buf, sent):
        """All complete, non-empty, non-echo lines in ``buf`` (bytes).

        Strips IAC and splits on newlines; the unterminated tail is ignored.
        Re-run on the whole buffer after every recv(), so IAC sequences and
        lines split across TCP segments reassemble correctly.
        """
        text = _strip_iac(bytes(buf)).replace(b"\r", b"")
        out = []
        for line in text.split(b"\n")[:-1]:  # [-1] is an incomplete tail
            s = line.decode("latin-1", "replace").strip()
            if s and s != sent:
                out.append(s)
        return out

    @staticmethod
    def _extract_reply(buf, sent):
        """Return the first reply line in ``buf``, or None if not yet complete."""
        lines = BiampNTP._complete_lines(buf, sent)
        return lines[0] if lines else None

    def _flush_pending(self):
        """Discard any unread stragglers from earlier exchanges (non-blocking).

        A prior command can leave trailing bytes on the wire (e.g. a late
        "-ERR:# 0x16" complaint); consumed here so they can't be misread as
        the next command's reply.
        """
        self._sock.settimeout(0.0)
        try:
            while self._sock.recv(4096):
                pass
        except (BlockingIOError, socket.timeout, OSError):
            pass

    def _read_reply(self, sent):
        """Read until a complete reply line arrives; return it ('' on timeout).

        The device echoes the command (telnet echo is on by default), then
        sends the reply terminated by CR/LF (`+OK`, `-ERR:...`, or a value).
        Returns as soon as that line is complete -- command rate is bounded
        by device RTT plus the small ``pace`` gap, not a fixed settle window.

        A "-ERR:# 0x..." line is the device complaining about command timing,
        normally followed by the real reply -- prefer the following line, but
        if nothing else arrives before ``timeout`` return the complaint itself
        so a genuine error is never swallowed. '' means the connection dropped
        or no reply completed within ``timeout``.
        """
        deadline = time.monotonic() + self.timeout
        buf = bytearray()
        busy = None
        while True:
            for s in self._complete_lines(buf, sent):
                if s.startswith("-ERR:#"):
                    busy = s          # timing complaint; real reply usually follows
                    continue
                return s
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return busy or ""
            self._sock.settimeout(remaining)
            try:
                b = self._sock.recv(4096)
            except socket.timeout:
                return busy or ""
            if not b:
                return busy or ""
            buf += b

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
                    wait = self._next_send - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)  # pace: keep the device below its choke rate
                    self._flush_pending()
                    self._sock.settimeout(self.timeout)
                    self._sock.sendall((text + "\n").encode())
                    last = self._read_reply(text.strip())
                    self._next_send = time.monotonic() + self.pace
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

    def recall_preset(self, preset):
        """RECALL a preset by number. Presets are system-wide (device 0)."""
        r = self.command("RECALL 0 PRESET %d" % int(preset))
        if r != "+OK":
            raise BiampError("RECALL PRESET %s -> %r" % (preset, r))
        return True

    def _adjust(self, verb, attr, inst, idx_and_amount):
        if not idx_and_amount:
            raise TypeError("%s() needs at least an amount" % verb.lower())
        idx, amount = idx_and_amount[:-1], idx_and_amount[-1]
        parts = [verb, str(self.device), attr, str(inst)]
        parts += [str(i) for i in idx] + [_fmt(amount)]
        r = self.command(" ".join(parts))
        if r != "+OK":
            raise BiampError("%s %s %s %s %s -> %r"
                             % (verb, attr, inst, list(idx), amount, r))
        return True

    def inc(self, attr, inst, *idx_and_amount):
        """INC an attribute by an amount (last positional). Returns True on +OK."""
        return self._adjust("INC", attr, inst, idx_and_amount)

    def dec(self, attr, inst, *idx_and_amount):
        """DEC an attribute by an amount (last positional). Returns True on +OK."""
        return self._adjust("DEC", attr, inst, idx_and_amount)
