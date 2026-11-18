#!/usr/bin/env python3
"""Markdown 原稿の文字数・見出し数・帯域判定を行う CLI ツール（標準ライブラリのみ）。

文字数の定義（固定）:
  - ファイルの1行目（タイトル行）のみ除外し、2行目以降の全行（見出し行を含む）を数える。
  - 空白（str.isspace() が真となる文字: 半角/全角スペース、タブ、改行など）は全て除いて数える。

帯域（下限・上限）の既定値は一例です。--min / --max で変更できます。
"""
import argparse
import sys

# 帯域の既定値（一例）
BAND_MIN = 1800
BAND_MAX = 2200
HEADING_PREFIX = "## "


def split_lines(text):
    """改行コード（\\r\\n / \\r / \\n）を統一して行に分割する。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


def body_lines(text):
    """1行目（タイトル行）を除いた行のリストを返す。"""
    return split_lines(text)[1:]


def count_chars(text):
    """本文（1行目以外）の非空白文字数を返す。"""
    return sum(1 for line in body_lines(text) for ch in line if not ch.isspace())


def count_headings(text):
    """本文（1行目以外）で行頭が「## 」で始まる行の数を返す。"""
    return sum(1 for line in body_lines(text) if line.startswith(HEADING_PREFIX))


def judge_band(n, lo=BAND_MIN, hi=BAND_MAX):
    """文字数の帯域判定（境界値は帯域内）。"""
    if n < lo:
        return "不足"
    if n > hi:
        return "超過"
    return "帯域内"


def check(text, lo=BAND_MIN, hi=BAND_MAX):
    n = count_chars(text)
    return {"chars": n, "headings": count_headings(text), "band": judge_band(n, lo, hi)}


def read_text(path):
    # utf-8-sig: 先頭に BOM があれば除去する
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def format_result(r, lo=BAND_MIN, hi=BAND_MAX):
    return (
        f"文字数: {r['chars']}\n"
        f"見出し数: {r['headings']}\n"
        f"帯域判定: {r['band']}（{lo:,}〜{hi:,}字）"
    )


def main(argv=None):
    # stdout のエラー処理を backslashreplace にし、
    # ロケール起因の UnicodeEncodeError で落ちないようにする。
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Markdown 原稿の文字数・見出し数・帯域判定")
    parser.add_argument("path", help="Markdown 原稿ファイルのパス")
    parser.add_argument("--min", type=int, default=BAND_MIN, help=f"帯域の下限（既定: {BAND_MIN}）")
    parser.add_argument("--max", type=int, default=BAND_MAX, help=f"帯域の上限（既定: {BAND_MAX}）")
    args = parser.parse_args(argv)
    try:
        text = read_text(args.path)
    except (OSError, UnicodeDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    # 出力先の異常（パイプ切断・ディスクフル等）を捕捉し、
    # トレースバック／終了時 flush エラーにせず終了コード2で終わる。
    try:
        print(format_result(check(text, args.min, args.max), args.min, args.max))
        sys.stdout.flush()
    except (OSError, UnicodeError, AttributeError) as e:
        # AttributeError は stdout が閉じている（>&- で sys.stdout が None）場合
        try:
            import os
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass
        try:
            print(f"エラー: 標準出力に書き込めません: {e}", file=sys.stderr)
        except Exception:
            pass
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
