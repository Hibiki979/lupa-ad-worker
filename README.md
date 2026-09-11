# lupa-ad-worker

LUPA（lupaselect.com）のAI広告動画の後工程ワーカー。GitHub Actions 上で動く。

- 10分おき（cron）に Shopify 上の非公開キューページ `https://lupaselect.com/pages/lupa-ad-queue-x7k2` の `<script id="lupa-queue">` JSON（`{"jobs":[...]}`）を読み、未処理ジョブを処理する。リポジトリの `queue/*.json` も同様に拾う（初期投入・手動用）
- `bin/process_job.py` が素材クリップをダウンロード → 1080x1920 に整形 → ハードカット結合 → 日本語字幕（Noto Sans CJK）→ ナレーション（gTTS）→ H.264/AAC
- 完成物は GitHub Release `job-<job_id>` の添付ファイルとして公開される：
  `<output_name>.mp4`、`frame1〜4.jpg`（検品用）、`result.json`、`<job_id>.log`
- 失敗しても Release は作られる（タイトルに `(failed)`、ログ添付）ので、呼び出し側は Release の有無だけ見ればよい
- 同じ job_id の Release が既にあれば再処理しない（冪等）

job.json の形式：

```json
{
  "job_id": "apron_0910_painA",
  "output_name": "apron_0910_painA_final.mp4",
  "beats": [
    {"source": "https://.../clip.mp4", "captions": [{"text": "…？", "start": 0, "end": 3, "style": "pain"}], "narration": "…"},
    {"source": "endcard", "duration": 2.5, "captions": [{"text": "¥4,850・送料無料\n今すぐチェック", "start": 0, "end": 2.5, "style": "cta"}], "narration": "…"}
  ]
}
```

手動で回す：Actions タブ → "LUPA ad post-production" → Run workflow（job_id 空欄で未処理分すべて）。
