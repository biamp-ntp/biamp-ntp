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


class Reply(unittest.TestCase):
    def setUp(self):
        self.c = BiampNTP("test.invalid")  # no connection is opened

    def test_strips_iac_and_takes_last_line(self):
        self.assertEqual(self.c._reply(b"\xff\xfb\x01-3.00\r\n"), "-3.00")

    def test_echo_then_value(self):
        raw = b"GET 1 OUTLVLPM 8 5\r\n-3.00\r\n"
        self.assertEqual(self.c._reply(raw), "-3.00")

    def test_ok(self):
        self.assertEqual(self.c._reply(b"SET 1 OUTLVLPM 8 5 -3.00\r\n+OK\r\n"), "+OK")

    def test_empty(self):
        self.assertEqual(self.c._reply(b"\xff\xfb\x01"), "")


if __name__ == "__main__":
    unittest.main()
