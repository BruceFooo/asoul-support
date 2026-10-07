"""log_stamp 的单元测试：每一行都要带秒级时间戳，且不能动原有的内容。"""

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import log_stamp  # noqa: E402


TIME = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
LINE = rf"^\[{TIME}\] "


class FakeStream:
    """够用的假流：能写、能 flush、带 encoding，用来验证属性透传。"""

    encoding = "utf-8"

    def __init__(self):
        self.parts = []
        self.flushed = False

    def write(self, text):
        self.parts.append(text)
        return len(text)

    def flush(self):
        self.flushed = True

    def fileno(self):
        return 42

    @property
    def text(self):
        return "".join(self.parts)


class StampedStreamTests(unittest.TestCase):
    def setUp(self):
        self.raw = FakeStream()
        self.stream = log_stamp._Stamped(self.raw)

    def test_prefixes_every_line(self):
        self.stream.write("一\n二\n")
        lines = self.raw.text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], rf"{LINE}一$")
        self.assertRegex(lines[1], rf"{LINE}二$")

    def test_print_splitting_text_and_newline_still_one_prefix(self):
        """print() 会先 write 内容再 write 换行，别因此多打一个时间戳。"""
        self.stream.write("半行")
        self.stream.write("补完")
        self.stream.write("\n")
        self.assertRegex(self.raw.text, rf"{LINE}半行补完\n$")

    def test_blank_line_gets_no_prefix(self):
        self.stream.write("一\n\n二\n")
        self.assertEqual(self.raw.text.splitlines()[1], "")

    def test_indentation_is_preserved(self):
        self.stream.write("  缩进两格\n")
        self.assertRegex(self.raw.text, rf"{LINE}  缩进两格\n$")

    def test_text_without_newline_keeps_a_single_prefix(self):
        self.stream.write("没有换行")
        self.assertEqual(self.raw.text.count("["), 1)

    def test_attributes_pass_through(self):
        self.assertEqual(self.stream.encoding, "utf-8")
        self.assertEqual(self.stream.fileno(), 42)

    def test_flush_reaches_the_underlying_stream(self):
        self.stream.flush()
        self.assertTrue(self.raw.flushed)

    def test_write_returns_length_like_a_real_stream(self):
        self.assertEqual(self.stream.write("abc"), 3)
        self.assertEqual(self.stream.write(""), 0)


class InstallTests(unittest.TestCase):
    def test_wraps_stdout_and_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", out), patch.object(sys, "stderr", err):
            log_stamp.install()
            self.assertIsInstance(sys.stdout, log_stamp._Stamped)
            self.assertIsInstance(sys.stderr, log_stamp._Stamped)
            print("走一遍真实路径")
        self.assertRegex(out.getvalue(), rf"{LINE}走一遍真实路径\n$")

    def test_install_twice_does_not_double_wrap(self):
        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", io.StringIO()), \
                patch.object(sys, "stderr", io.StringIO()):
            log_stamp.install()
            once = sys.stdout
            log_stamp.install()
            self.assertIs(sys.stdout, once)

    def test_none_streams_are_left_alone(self):
        """pythonw 没重定向时 sys.stdout 是 None，包起来只会炸。"""
        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            log_stamp.install()
            self.assertIsNone(sys.stdout)
            self.assertIsNone(sys.stderr)


class LineBufferTests(unittest.TestCase):
    """重定向到文件时默认按 8KB 块缓冲，长跑的挂机进程日志会长时间不落盘。"""

    def test_install_switches_both_streams_to_line_buffering(self):
        calls = []

        class _Reconfigurable(io.StringIO):
            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", _Reconfigurable()), \
                patch.object(sys, "stderr", _Reconfigurable()):
            log_stamp.install()
        self.assertEqual(calls, [{"line_buffering": True}, {"line_buffering": True}])

    def test_stream_without_reconfigure_is_not_fatal(self):
        """pythonw、或已经被别人包装过的流没有 reconfigure，不能因此炸掉。"""
        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", FakeStream()), \
                patch.object(sys, "stderr", FakeStream()):
            log_stamp.install()
            self.assertIsInstance(sys.stdout, log_stamp._Stamped)

    def test_stdout_can_be_left_alone(self):
        """stdout 是机器可读数据时（heartbeat --json）不能加前缀，否则调用方解析不了。"""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(log_stamp, "_installed", False), \
                patch.object(sys, "stdout", out), patch.object(sys, "stderr", err):
            log_stamp.install(stdout=False)
            self.assertIs(sys.stdout, out)                      # 原样透出去，没被包
            self.assertIsInstance(sys.stderr, log_stamp._Stamped)
            print("只该出现在 stderr", file=sys.stderr)
        self.assertEqual(out.getvalue(), "")
        self.assertRegex(err.getvalue(), rf"{LINE}只该出现在 stderr\n$")


if __name__ == "__main__":
    unittest.main()
