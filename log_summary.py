"""構造化行「LOG|YYYY-MM-DD|種別|分」を集計する小さなユーティリティ。

使い方:
    python3 tools/log_summary.py [FILE ...]
    python3 tools/log_summary.py --self-test

FILE を省略するか "-" を指定すると標準入力を読みます。複数の入力は合算します。
入力は UTF-8（BOM 可、改行は LF/CRLF/CR）として読みます。標準ライブラリのみを使用します。

行の扱い:
- 各行の全角英数字・記号（ＬＯＧ・｜・数字・－ など）と全角空白を半角にし、BOM や
  ゼロ幅空白などの不可視の書式文字を除いてから "|" で区切ります。先頭の項目が LOG の行を
  LOG 行とし、それ以外の行は無視します（LOGIN|…、log|…、行の途中の LOG| も無視）。
  上付き数字や丸数字など、全角以外の互換文字は変換しません。
- LOG 行はちょうど4項目「LOG|日付|種別|分」で、各項目の前後の空白は無視します。
  日付は実在する YYYY-MM-DD、種別は 判断・操作・確認・指示 のいずれか（NFKC 正規化して
  比較）、分は9桁までの整数（符号可。訂正用の負数も集計します）です。
- これに合わない LOG 行（LOG だけの行を含む項目不足・項目過多・空の項目・分が整数でない・
  10桁以上の分・実在しない日付・未知の種別）は「形式エラー」として件数だけ数え、
  集計に入れません。

出力（標準出力）:
    種別ごと:
      判断: 2件 45分
      操作: 1件 45分
      確認: 2件 25分
      指示: 2件 30分
    月ごと:
      2025-12: 20分
      2026-10: 15分
      2026-11: 110分
    全体合計: 7件 145分
    形式エラー: 0件

種別は常に4種を表示し、月は昇順です。LOG 行が無ければ各値は0、月ごとは (なし) です。

終了コード:
    0  集計を出力した（形式エラーがあっても0）
    2  ファイルや標準入力を読めない、または UTF-8 として解釈できない（集計は出力しない）
    --self-test は全テスト成功で0、失敗があれば（テストが1件も実行されない場合も）1。
"""

import argparse
import contextlib
import datetime
import io
import os
import re
import sys
import tempfile
import unicodedata
import unittest

KINDS = ("判断", "操作", "確認", "指示")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_MINUTES = re.compile(r"[+-]?[0-9]{1,9}")
# 全角 ASCII（U+FF01〜U+FF5E）と全角空白だけを半角にする。行全体の NFKC は上付き数字や
# 丸数字まで数字に変えてしまう（30 と上付き 1 が 301 になる）ため使わない。
_HALFWIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}
_HALFWIDTH[0x3000] = 0x20


class InputError(Exception):
    """入力を読めない、または UTF-8 として解釈できない。"""


def _normalize(line):
    """不可視の書式文字（Unicode の Cf: BOM・ゼロ幅空白など）を除き、全角 ASCII と全角空白を半角にする。"""
    if not line.isprintable():
        line = "".join(char for char in line if unicodedata.category(char) != "Cf")
    return line.translate(_HALFWIDTH)


def _parse_fields(fields):
    """LOG 行の項目リストを検証し、(日付, 種別, 分) を返す。形式エラーなら None。"""
    if len(fields) != 4:
        return None
    date_text, kind, minutes_text = (field.strip() for field in fields[1:])
    kind = unicodedata.normalize("NFKC", kind)  # 康熙部首などの互換漢字を通常の漢字にそろえる
    date_match = _DATE.fullmatch(date_text)
    if date_match is None or kind not in KINDS or _MINUTES.fullmatch(minutes_text) is None:
        return None
    try:
        datetime.date(*(int(part) for part in date_match.groups()))
    except ValueError:  # 実在しない日付
        return None
    return date_text, kind, int(minutes_text)


def summarize(lines):
    """行の並びを集計し、{"kinds", "months", "total", "format_errors"} の辞書を返す。

    kinds は {種別: {"count": 件数, "minutes": 分}}（4種すべて）、months は {"YYYY-MM": 分}、
    total は {"count": 件数, "minutes": 分}、format_errors は形式エラーの件数。
    """
    kinds = {kind: {"count": 0, "minutes": 0} for kind in KINDS}
    months = {}
    format_errors = 0
    for line in lines:
        fields = _normalize(line).split("|")
        if fields[0].strip() != "LOG":
            continue
        entry = _parse_fields(fields)
        if entry is None:
            format_errors += 1
            continue
        date_text, kind, minutes = entry
        kinds[kind]["count"] += 1
        kinds[kind]["minutes"] += minutes
        months[date_text[:7]] = months.get(date_text[:7], 0) + minutes
    total = {"count": sum(item["count"] for item in kinds.values()),
             "minutes": sum(item["minutes"] for item in kinds.values())}
    return {"kinds": kinds, "months": months, "total": total, "format_errors": format_errors}


def render(summary):
    """summarize() の結果を表示用の文字列にする。"""
    lines = ["種別ごと:"]
    for kind in KINDS:
        item = summary["kinds"][kind]
        lines.append(f"  {kind}: {item['count']}件 {item['minutes']}分")
    lines.append("月ごと:")
    months = summary["months"]
    lines.extend(f"  {month}: {months[month]}分" for month in sorted(months))
    if not months:
        lines.append("  (なし)")
    total = summary["total"]
    lines.append(f"全体合計: {total['count']}件 {total['minutes']}分")
    lines.append(f"形式エラー: {summary['format_errors']}件")
    return "\n".join(lines) + "\n"


def _read_bytes(path, stdin):
    """1つの入力をバイト列で読む。"-" は標準入力（stdin が None なら sys.stdin）を読む。"""
    if path != "-":
        with open(path, "rb") as handle:
            return handle.read()
    stream = getattr(sys.stdin, "buffer", None) if stdin is None else stdin
    if stream is None:  # 標準入力（fd 0）が閉じていると sys.stdin は None になる
        raise OSError("標準入力が閉じています")
    return stream.read()


def read_lines(paths, stdin=None):
    """各入力（"-" と省略時は標準入力）を読んで行のリストを返す。

    stdin はバイナリストリームで、None なら sys.stdin を使う。標準入力は "-" を読むときだけ
    参照する。読めない入力や UTF-8 として解釈できない入力は InputError にする。
    """
    lines = []
    for path in paths or ["-"]:
        name = "標準入力" if path == "-" else path
        try:
            data = _read_bytes(path, stdin)
        except OSError as exc:
            raise InputError(f"{name}: 読めません（{exc.strerror or exc}）") from None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            head = data[:exc.start].replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            line_number = head.count(b"\n") + 1
            raise InputError(f"{name}: {line_number}行目を UTF-8 として解釈できません") from None
        lines.extend(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return lines


def main(argv=None, stdin=None, stdout=None, stderr=None):
    """CLI の入口。終了コードを返す。stdin はバイナリ、stdout と stderr はテキストのストリーム。"""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(
        description="LOG|YYYY-MM-DD|種別|分 の行を集計し、種別ごとの件数と合計分、"
                    "月ごとの合計分、全体の合計、形式エラーの件数を表示します。",
        allow_abbrev=False,
    )
    parser.add_argument("files", nargs="*", metavar="FILE",
                        help='入力ファイル（省略時と "-" は標準入力。複数指定は合算）')
    parser.add_argument("--self-test", action="store_true",
                        help="組み込みテストを実行する（全て成功で終了コード0、失敗があれば1）")
    args = parser.parse_args(argv)
    if args.self_test:
        if args.files:
            parser.error("--self-test はファイル引数と併用できません")
        return run_self_test(stdout)
    try:
        lines = read_lines(args.files, stdin)
    except InputError as exc:
        print(f"エラー: {exc}", file=stderr)
        return 2
    stdout.write(render(summarize(lines)))
    return 0


ZERO_OUTPUT = (
    "種別ごと:\n"
    "  判断: 0件 0分\n"
    "  操作: 0件 0分\n"
    "  確認: 0件 0分\n"
    "  指示: 0件 0分\n"
    "月ごと:\n"
    "  (なし)\n"
    "全体合計: 0件 0分\n"
    "形式エラー: 0件\n"
)


class SelfTest(unittest.TestCase):
    """--self-test で実行する組み込みテスト。"""

    def run_main(self, argv, stdin=b""):
        """main() を実行して (終了コード, 標準出力, 標準エラー) を返す。stdin はバイト列かストリーム。"""
        out, err = io.StringIO(), io.StringIO()
        if isinstance(stdin, bytes):
            stdin = io.BytesIO(stdin)
        code = main(argv, stdin=stdin, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def write_file(self, directory, name, data):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def assert_summary(self, data, kinds, months, total, errors):
        """data（バイト列）の集計を比べる。kinds は {種別: (件数, 分)} で、省略した種別は (0, 0)。"""
        self.assertEqual(summarize(read_lines([], io.BytesIO(data))), {
            "kinds": {kind: dict(zip(("count", "minutes"), kinds.get(kind, (0, 0))))
                      for kind in KINDS},
            "months": months,
            "total": dict(zip(("count", "minutes"), total)),
            "format_errors": errors,
        })

    def test_1_normal_lines(self):
        """正常な複数行の集計（種別・月・全体。LOG 以外の行は無視、月は昇順）"""
        data = (
            "# 作業メモ\n"
            "LOG|2026-11-01|判断|30\n"
            "LOG|2026-11-01|操作|45\n"
            "今日は確認が多かった\n"
            "LOG|2026-11-02|確認|20\n"
            "LOG|2026-11-03|指示|10\n"
            "LOG|2026-11-03|確認|5\n"
            "LOG|2026-10-31|判断|15\n"
            "LOG|2025-12-28|指示|20\n"
        ).encode("utf-8")
        self.assertEqual(self.run_main([], data), (0, (
            "種別ごと:\n"
            "  判断: 2件 45分\n"
            "  操作: 1件 45分\n"
            "  確認: 2件 25分\n"
            "  指示: 2件 30分\n"
            "月ごと:\n"
            "  2025-12: 20分\n"
            "  2026-10: 15分\n"
            "  2026-11: 110分\n"
            "全体合計: 7件 145分\n"
            "形式エラー: 0件\n"
        ), ""))

    def test_2_format_errors(self):
        """形式エラー行（項目不足・分が数値でない等）は件数だけ数え、集計に入れない"""
        malformed = [
            "LOG",                             # 項目不足
            "LOG|2026-11-01|判断",
            "LOG|2026-11-01",
            "LOG|",
            "LOG|2026-11-01||30",              # 空の項目
            "LOG||判断|30",
            "LOG|2026-11-01|操作|",
            "LOG|2026-11-01|操作|abc",         # 分が整数でない
            "LOG|2026-11-01|操作|30分",
            "LOG|2026-11-01|操作|1.5",
            "LOG|2026-11-01|操作|--5",
            "LOG|2026-11-01|操作|30\u00b9",    # 上付き数字・全角以外の数字は数字として扱わない
            "LOG|2026-11-01|操作|\u0663\u0660",
            "LOG|2026-11-01|操作|1000000000",  # 10桁以上
            "LOG|2026-02-29|確認|10",          # 実在しない日付・日付形式の違い
            "LOG|2026/11/01|確認|10",
            "LOG|2026-1-05|確認|10",
            "LOG|2026-11-5|確認|10",
            "LOG|\u0662\u0660\u0662\u0666-11-01|確認|10",
            "LOG|2026-11-01|雑務|10",          # 未知の種別
            "LOG|2026-11-01|指示|10|メモ",     # 項目過多
            "LOG|2026-11-01|指示|10|",
        ]
        valid = ["LOG|2026-11-05|判断|30", "LOG|2024-02-29|指示|0", "LOG|2026-11-06|判断|-10",
                 "LOG|2026-11-06|確認|+5", "LOG|2026-11-07|操作|000000045"]
        ignored = ["LOGIN|2026-11-01|判断|30", "log|2026-11-01|判断|30", "## LOG",
                   "メモ: LOG|2026-11-01|判断|30", "| LOG | 2026-11-01 | 判断 | 30 |"]
        data = "\n".join(malformed[:8] + valid[:2] + ignored + malformed[8:] + valid[2:]).encode("utf-8")
        self.assert_summary(data, {"判断": (2, 20), "操作": (1, 45), "確認": (1, 5), "指示": (1, 0)},
                            {"2026-11": 70, "2024-02": 0}, (5, 70), len(malformed))
        code, out, err = self.run_main([], data)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.endswith("全体合計: 5件 70分\n形式エラー: 22件\n"), out)

    def test_3_no_log_lines(self):
        """LOG 行が無い入力は全て0で正常終了（終了コード0）"""
        for data in (b"", b"\n\n", "# メモ\n今日は記録なし\n| 表 | です |\n".encode("utf-8")):
            with self.subTest(data=data):
                self.assertEqual(self.run_main([], data), (0, ZERO_OUTPUT, ""))

    def test_4_notation_variants(self):
        """前後の空白・全角表記・不可視の書式文字・康熙部首・CRLF/CR 改行の LOG 行も集計する"""
        data = (
            "\ufeffLOG|2026-11-01|判断|10\r\n"       # 先頭の BOM
            "  LOG | 2026-11-01 | 操作 | 20  \r\n"
            "ＬＯＧ｜２０２６－１１－０２｜確認｜３０\r"
            "\tLOG|2026-12-01|指示|040\n"
            "\ufeffLOG|2026-12-02|判断|5\n"          # 連結した入力の途中の BOM
            "\u3000LOG|2026-12-03|操作|1\u3000\n"
            "\u200bLOG|2026-12-04|確認|\u200e7\n"    # ゼロ幅空白と LRM
            "LOG|2026-12-05|指\u2f70|4\n"            # 康熙部首の「示」
        ).encode("utf-8")
        self.assert_summary(data, {"判断": (2, 15), "操作": (2, 21), "確認": (2, 37), "指示": (2, 44)},
                            {"2026-11": 60, "2026-12": 57}, (8, 117), 0)

    def test_5_file_arguments(self):
        """複数のファイル引数と "-"（標準入力）を合算する"""
        with tempfile.TemporaryDirectory() as tmp:
            first = self.write_file(tmp, "a.txt", "LOG|2026-11-01|判断|10\nメモ\n".encode("utf-8"))
            second = self.write_file(
                tmp, "b.md", "\ufeffLOG|2026-12-01|操作|20\r\nLOG|2026-12-01|操作|x\r\n".encode("utf-8"))
            result = self.run_main([first, second, "-"], "LOG|2026-12-02|確認|5\n".encode("utf-8"))
        self.assertEqual(result, (0, (
            "種別ごと:\n"
            "  判断: 1件 10分\n"
            "  操作: 1件 20分\n"
            "  確認: 1件 5分\n"
            "  指示: 0件 0分\n"
            "月ごと:\n"
            "  2026-11: 10分\n"
            "  2026-12: 25分\n"
            "全体合計: 3件 35分\n"
            "形式エラー: 1件\n"
        ), ""))

    def test_6_unreadable_input(self):
        """読めないファイルや UTF-8 でない入力は終了コード2で、集計を出力しない（行番号を示す）"""
        with tempfile.TemporaryDirectory() as tmp:
            good = self.write_file(tmp, "good.txt", "LOG|2026-11-01|判断|10\n".encode("utf-8"))
            sjis = self.write_file(tmp, "sjis.txt", "LOG|2026-11-01|判断|10\r\n".encode("utf-8")
                                   + b"memo\rok\n" + "メモ\r\n".encode("cp932"))
            cases = (
                ([good, os.path.join(tmp, "missing.txt")], b"", "missing.txt: 読めません"),
                ([good, tmp], b"", tmp + ": 読めません"),
                ([good, sjis], b"", "sjis.txt: 4行目を UTF-8 として解釈できません"),
                ([good, "-"], b"ok\n" + "判断".encode("cp932"), "標準入力: 2行目を UTF-8 として解釈できません"),
            )
            for argv, stdin, message in cases:
                with self.subTest(argv=argv):
                    code, out, err = self.run_main(argv, stdin)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(message, err)

    def test_7_stdin_unavailable(self):
        """標準入力が閉じている・読めないとき、ファイル引数だけなら集計し、標準入力を読むなら終了コード2"""
        from unittest import mock

        class Unreadable:
            def read(self):
                raise OSError(5, "Input/output error")

        with tempfile.TemporaryDirectory() as tmp:
            good = self.write_file(tmp, "good.txt", "LOG|2026-11-01|判断|10\n".encode("utf-8"))
            with mock.patch.object(sys, "stdin", None):  # 標準入力（fd 0）が閉じた状態
                closed = [self.run_main([good], None), self.run_main([], None)]
            unreadable = [self.run_main([good], Unreadable()), self.run_main([good, "-"], Unreadable())]
        for code, out, err in (closed[0], unreadable[0]):
            self.assertEqual((code, err), (0, ""))
            self.assertTrue(out.endswith("全体合計: 1件 10分\n形式エラー: 0件\n"), out)
        self.assertEqual(closed[1], (2, "", "エラー: 標準入力: 読めません（標準入力が閉じています）\n"))
        self.assertEqual(unreadable[1], (2, "", "エラー: 標準入力: 読めません（Input/output error）\n"))

    def test_8_self_test_result(self):
        """--self-test は全て成功で0、失敗・エラー・テスト0件で1（サブテストの失敗は1件と数える）"""
        from unittest import mock

        class Mixed(unittest.TestCase):
            def test_ok(self):
                pass

            def test_fail(self):
                self.fail("意図的な失敗")

            def test_error(self):
                raise RuntimeError("意図的なエラー")

            def test_subtests(self):
                for number in (1, 2):
                    with self.subTest(number=number):
                        self.fail("意図的な失敗")

        class Passing(unittest.TestCase):
            def test_pass(self):
                pass

        class Empty(unittest.TestCase):
            pass

        cases = (
            (Mixed, 1, "self-test: 4件中 1件成功（失敗 3件）\n"),
            (Passing, 0, "self-test: 1件中 1件成功\n"),
            (Empty, 1, "self-test: 0件中 0件成功（テストが実行されませんでした）\n"),
        )
        for case, code, summary in cases:
            with self.subTest(case=case.__name__):
                out = io.StringIO()
                # main() から終了コードまでの経路はそのままに、実行するテストクラスだけ差し替える
                with mock.patch.dict(globals(), SelfTest=case):
                    self.assertEqual(main(["--self-test"], stdout=out), code)
                self.assertTrue(out.getvalue().endswith(summary), out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["--self-test", "a.txt"])
        self.assertEqual(caught.exception.code, 2)


class _Result(unittest.TextTestResult):
    """成功したテストを数える（サブテストが失敗したテスト・スキップ・予期しない成功は含めない）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.succeeded = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.succeeded += 1


def run_self_test(stream):
    """組み込みテスト SelfTest を実行し、全て成功なら0、失敗があれば（テスト0件も）1を返す。"""
    suite = unittest.TestLoader().loadTestsFromTestCase(SelfTest)
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=_Result).run(suite)
    ok = result.wasSuccessful() and result.testsRun > 0
    passed = result.succeeded + len(result.expectedFailures)
    failed = result.testsRun - passed - len(result.skipped)
    notes = []
    if failed:
        notes.append(f"失敗 {failed}件")
    if result.skipped:
        notes.append(f"スキップ {len(result.skipped)}件")
    if not result.testsRun:
        notes.append("テストが実行されませんでした")
    elif not ok and not failed:
        notes.append("テスト以外のエラーあり")  # setUpClass などの準備・後始末での失敗
    note = "（" + "、".join(notes) + "）" if notes else ""
    print(f"self-test: {result.testsRun}件中 {passed}件成功{note}", file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
