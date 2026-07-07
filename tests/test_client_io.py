"""I/O tests against a fake Nexia telnet server -- no hardware needed.

Covers the parts the unit tests can't: reply framing across split TCP
segments, IAC interleaved with replies, command echo handling, the
reconnect-retry path, and timeout behaviour.
"""
import socket
import threading
import time
import unittest

from biamp_ntp.client import BiampNTP, BiampError

IAC_WILL_ECHO = b"\xff\xfb\x01"
IAC_DO_SGA = b"\xff\xfd\x03"


class FakeNexia:
    """Minimal scripted telnet server.

    ``script`` is a list of per-connection handler callables; connection N
    is served by script[N] (the last entry repeats). Each handler gets the
    accepted socket and is responsible for the whole session.
    """

    def __init__(self, script):
        self.script = script
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.connections = 0
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            handler = self.script[min(self.connections, len(self.script) - 1)]
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn, handler),
                             daemon=True).start()

    @staticmethod
    def _handle(conn, handler):
        try:
            handler(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self.srv.close()


def _recv_line(conn):
    """Read one \\n-terminated command from the client."""
    buf = bytearray()
    while not buf.endswith(b"\n"):
        b = conn.recv(1024)
        if not b:
            return None
        buf += b
    return bytes(buf[:-1])


def echo_and_reply(reply, banner=IAC_WILL_ECHO, chunks=None, delay=0.0,
                   echo=True):
    """Build a handler: send banner, then serve commands with ``reply``.

    ``chunks`` optionally splits the reply bytes to simulate the device
    dribbling the frame across TCP segments; ``delay`` sleeps between them.
    """
    def handler(conn):
        if banner:
            conn.sendall(banner)
        while True:
            cmd = _recv_line(conn)
            if cmd is None:
                return
            if echo:
                conn.sendall(cmd + b"\r\n")
            payload = reply if callable(reply) is False else reply
            parts = chunks or [payload]
            for part in parts:
                if delay:
                    time.sleep(delay)
                conn.sendall(part)
    return handler


class ClientIO(unittest.TestCase):
    def _client(self, server, **kw):
        kw.setdefault("timeout", 2.0)
        kw.setdefault("settle", 0.02)   # keep the connect drain fast in tests
        return BiampNTP("127.0.0.1", port=server.port, **kw)

    def test_get_with_echo_and_iac(self):
        srv = FakeNexia([echo_and_reply(b"-3.00 \r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertEqual(dsp.get("OUTLVLPM", 8, 5), "-3.00")

    def test_set_ok(self):
        srv = FakeNexia([echo_and_reply(b"+OK\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertTrue(dsp.set("OUTLVLPM", 8, 5, -6.0))

    def test_reply_dribbled_across_segments(self):
        # echo, then the value split mid-line AND mid-IAC-triple
        srv = FakeNexia([echo_and_reply(
            None,
            chunks=[b"\xff", b"\xfb\x01-12.", b"50 \r", b"\n"],
            delay=0.05)])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertEqual(dsp.get_float("OUTLVLPM", 8, 5), -12.50)

    def test_err_raises(self):
        srv = FakeNexia([echo_and_reply(b"-ERR:XACTION ERROR\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            with self.assertRaises(BiampError):
                dsp.get("OUTLVLPM", 199, 1)

    def test_no_echo_still_parses(self):
        srv = FakeNexia([echo_and_reply(b"1\r\n", echo=False)])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertEqual(dsp.device_id(), 1)

    def test_reconnect_retry_after_silent_drop(self):
        # first connection: banner then immediate close (empty reply);
        # second connection: answers normally. command() must retry once.
        def drop(conn):
            conn.sendall(IAC_WILL_ECHO)
            _recv_line(conn)        # swallow the command, reply with nothing
            conn.close()
        srv = FakeNexia([drop, echo_and_reply(b"+OK\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertTrue(dsp.set("OUTMUTEPM", 8, 5, True))
        self.assertEqual(srv.connections, 2)

    def test_timeout_returns_empty_then_error(self):
        def mute(conn):             # never replies
            conn.sendall(IAC_DO_SGA)
            while _recv_line(conn) is not None:
                pass
        srv = FakeNexia([mute])
        self.addCleanup(srv.close)
        dsp = self._client(srv, timeout=0.3)
        with dsp:
            t0 = time.monotonic()
            with self.assertRaises(BiampError):
                dsp.get("OUTLVLPM", 8, 5)
            # one attempt + one retry, each bounded by timeout (+ slack)
            self.assertLess(time.monotonic() - t0, 2.0)

    def test_command_rate_is_rtt_bound(self):
        # With pacing disabled, 20 commands should complete far faster than
        # the old settle-based framing (~0.4s each -> ~8s).
        srv = FakeNexia([echo_and_reply(b"+OK\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv, pace=0.0) as dsp:
            t0 = time.monotonic()
            for _ in range(20):
                dsp.command("GET 1 OUTLVLPM 8 5")
            self.assertLess(time.monotonic() - t0, 1.0)

    def test_pace_floor_between_commands(self):
        # Commands on one connection must be spaced >= pace: real hardware
        # emits -ERR:# 0x16 and falls behind when pipelined at full rate.
        stamps = []

        def stamping(conn):
            conn.sendall(IAC_WILL_ECHO)
            while True:
                cmd = _recv_line(conn)
                if cmd is None:
                    return
                stamps.append(time.monotonic())
                conn.sendall(cmd + b"\r\n+OK\r\n")

        srv = FakeNexia([stamping])
        self.addCleanup(srv.close)
        with self._client(srv, pace=0.08) as dsp:
            for _ in range(4):
                dsp.command("SET 1 OUTMUTEPM 8 5 0")
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertTrue(all(g >= 0.07 for g in gaps),
                        "command gaps below pace floor: %s" % gaps)

    # -- "-ERR:# 0x16" regression (observed on a live Nexia PM) -----------
    # Under command pressure the device prepends an undocumented
    # "-ERR:# 0x16" line to its real reply. Taking it as the answer
    # desynchronizes reply attribution for every later command.

    def test_busy_line_before_real_reply_is_skipped(self):
        srv = FakeNexia([echo_and_reply(b"-ERR:# 0x16\r\n-3.00 \r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertEqual(dsp.get("OUTLVLPM", 8, 5), "-3.00")

    def test_busy_line_before_error_reports_the_real_error(self):
        srv = FakeNexia([echo_and_reply(b"-ERR:# 0x16\r\n-ERR:XACTION ERROR\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            with self.assertRaises(BiampError) as cm:
                dsp.get("OUTLVLPM", 199, 1)
            self.assertIn("XACTION", str(cm.exception))

    def test_sole_busy_line_is_returned_not_swallowed(self):
        # If nothing follows the complaint, it must surface as the reply
        # (after the timeout grace) rather than vanish.
        srv = FakeNexia([echo_and_reply(b"-ERR:# 0x16\r\n")])
        self.addCleanup(srv.close)
        dsp = self._client(srv, timeout=0.3)
        with dsp:
            self.assertEqual(dsp.query("OUTLVLPM", 8, 5), "-ERR:# 0x16")

    def test_busy_lines_across_many_commands_stay_aligned(self):
        # Every reply carries the 0x16 prefix; attribution must not drift
        # (this is the exact live-scan failure mode).
        values = [b"-1.00", b"-2.00", b"-3.00", b"-4.00", b"-5.00"]
        state = {"n": 0}

        def handler(conn):
            conn.sendall(IAC_WILL_ECHO)
            while True:
                cmd = _recv_line(conn)
                if cmd is None:
                    return
                v = values[state["n"] % len(values)]
                state["n"] += 1
                conn.sendall(cmd + b"\r\n-ERR:# 0x16\r\n" + v + b" \r\n")

        srv = FakeNexia([handler])
        self.addCleanup(srv.close)
        with self._client(srv, pace=0.0) as dsp:
            got = [dsp.get("OUTLVLPM", 8, i) for i in range(1, 6)]
        self.assertEqual(got, ["-1.00", "-2.00", "-3.00", "-4.00", "-5.00"])

    def test_recall_inc_dec_wire_format(self):
        received = []

        def capture(conn):
            conn.sendall(IAC_WILL_ECHO)
            while True:
                cmd = _recv_line(conn)
                if cmd is None:
                    return
                received.append(cmd.decode())
                conn.sendall(cmd + b"\r\n+OK\r\n")

        srv = FakeNexia([capture])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            self.assertTrue(dsp.recall_preset(1001))
            self.assertTrue(dsp.inc("OUTLVLPM", 8, 5, 2))
            self.assertTrue(dsp.dec("OUTLVLPM", 8, 5, 1.5))
        self.assertEqual(received, [
            "RECALL 0 PRESET 1001",
            "INC 1 OUTLVLPM 8 5 2",
            "DEC 1 OUTLVLPM 8 5 1.5",
        ])

    def test_recall_error_raises(self):
        srv = FakeNexia([echo_and_reply(b"-ERR:SYNTAX\r\n")])
        self.addCleanup(srv.close)
        with self._client(srv) as dsp:
            with self.assertRaises(BiampError):
                dsp.recall_preset(9999)


if __name__ == "__main__":
    unittest.main()
