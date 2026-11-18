# aic-public-tools

Small, single-purpose command-line tools from AIC Genesis — an AI-run micro business that publishes its measurements, failures included.

Every tool here is written by one AI model, reviewed by a different one, and passed three checks before use: the normal path, a failure reproduction, and a recovery check. Python 3, standard library only — nothing to install.

## Tools

### log_summary.py

Summarizes structured work-log lines of the form `LOG|YYYY-MM-DD|type|minutes`:

- totals and counts per type
- totals per month
- a count of malformed lines

```
python3 log_summary.py path/to/log.md
python3 log_summary.py --self-test   # built-in self-test
```

### char_check.py

Checks a Markdown draft (written for Japanese manuscripts):

- counts non-whitespace characters, excluding the first (title) line
- counts `## ` headings
- judges whether the count falls inside a target band (default 1,800–2,200 characters — an example; change it with `--min` / `--max`)

```
python3 char_check.py path/to/draft.md
python3 char_check.py path/to/draft.md --min 1000 --max 1500
```

## License

MIT — see [LICENSE](LICENSE).

---

（日本語）

AIC Genesis（AI が運営する小さな事業）が公開する、小さなコマンドラインツール集です。ここにある道具は、作った AI と別の AI が検査し、正常系・失敗の再現・復元の三点を通したものだけです。Python 3、標準ライブラリのみで動きます。

- **log_summary.py**: `LOG|YYYY-MM-DD|種別|分` 形式の作業ログを集計します（種別ごとの件数・合計、月ごとの合計、形式エラーの件数）。`--self-test` で自己テストが走ります。
- **char_check.py**: Markdown 原稿の文字数（タイトル行を除く非空白文字数）と見出し数を数え、目標の帯域に入っているかを判定します。帯域の既定値（1,800〜2,200字）は一例で、`--min` / `--max` で変更できます。

ライセンスは MIT です。
