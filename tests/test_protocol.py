"""Unit tests that need no hardware -- parsing, IAC stripping, wire formatting."""
import unittest

from biamp_ntp.client import BiampNTP, _fmt, _strip_iac


class StripIAC(unittest.TestCase):
    def test_single_triple(self):
        # IAC WILL ECHO (0xFF 0xFB 0x01) prefixing "+OK"
        self.assertEqual(_strip_iac(b"\xff\xfb\x01+OK\r\n"), b"+OK\r\n")

    def test_multiple_triples(self):
        self.assertEqual(_strip_iac(b"\xff\xfd\x03\xff\xfb\x01-3.00\r\n"), b"-3.00\r\n")

    def test_no_iac(self):
        self.assertEqual(_strip_iac(b"-3.00\r\n"), b"-3.00\r\n")

    def test_escaped_literal_ff(self):
        # IAC IAC is an escaped 0xFF data byte, not a command
        self.assertEqual(_strip_iac(b"a\xff\xffb"), b"a\xffb")

    def test_subnegotiation_skipped_whole(self):
        # IAC SB TTYPE ... IAC SE is longer than a triple
        raw = b"\xff\xfa\x18\x01payload\xff\xf0+OK\r\n"
        self.assertEqual(_strip_iac(raw), b"+OK\r\n")

    def test_two_byte_command(self):
        # IAC NOP (0xFF 0xF1) is a 2-byte command
        self.assertEqual(_strip_iac(b"\xff\xf1+OK\r\n"), b"+OK\r\n")

    def test_partial_tail_waits(self):
        # incomplete sequences at the tail must not consume following bytes
        self.assertEqual(_strip_iac(b"+OK\r\n\xff"), b"+OK\r\n")
        self.assertEqual(_strip_iac(b"+OK\r\n\xff\xfb"), b"+OK\r\n")
        self.assertEqual(_strip_iac(b"+OK\r\n\xff\xfa\x18"), b"+OK\r\n")


class Fmt(unittest.TestCase):
    def test_bool(self):
        self.assertEqual(_fmt(True), "1")
        self.assertEqual(_fmt(False), "0")

    def test_float(self):
        self.assertEqual(_fmt(1.0), "1")
        self.assertEqual(_fmt(-3.5), "-3.5")
        self.assertEqual(_fmt(0.0), "0")
        self.assertEqual(_fmt(-6.25), "-6.25")

    def test_int_and_str(self):
        self.assertEqual(_fmt(5), "5")
        self.assertEqual(_fmt("on"), "on")


class ExtractReply(unittest.TestCase):
    x = staticmethod(BiampNTP._extract_reply)

    def test_strips_iac(self):
        self.assertEqual(self.x(b"\xff\xfb\x01-3.00\r\n", ""), "-3.00")

    def test_skips_echo_takes_value(self):
        sent = "GET 1 OUTLVLPM 8 5"
        raw = b"GET 1 OUTLVLPM 8 5\r\n-3.00 \r\n"
        self.assertEqual(self.x(raw, sent), "-3.00")

    def test_ok_after_echo(self):
        sent = "SET 1 OUTLVLPM 8 5 -3.00"
        raw = b"SET 1 OUTLVLPM 8 5 -3.00\r\n+OK\r\n"
        self.assertEqual(self.x(raw, sent), "+OK")

    def test_incomplete_returns_none(self):
        sent = "GET 1 OUTLVLPM 8 5"
        # echo complete, value line not yet terminated
        self.assertIsNone(self.x(b"GET 1 OUTLVLPM 8 5\r\n-3.0", sent))
        # bare IAC negotiation only
        self.assertIsNone(self.x(b"\xff\xfb\x01", sent))

    def test_iac_split_reassembles(self):
        # trailing partial IAC triple must not corrupt an earlier line
        self.assertEqual(self.x(b"+OK\r\n\xff", ""), "+OK")


if __name__ == "__main__":
    unittest.main()
