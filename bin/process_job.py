#!/usr/bin/env python3
# LUPA AI creative post-production (GitHub Actions worker). 2026-09-11: narration 1.5x + BGM bed.
# Usage: process_job.py <job.json> <out_dir>
#
# job.json format:
# {
#   "job_id": "20260910_nekosuna_v2",
#   "output_name": "nekosuna_mat_v2_final.mp4",
#   "voice": "Kyoko",                 # optional, macOS `say` voice
#   "bgm": "https://.../track.mp3",   # optional; default assets/bgm/default.mp3 if present
#   "beats": [
#     {"source": "https://.../clip1.mp4", "duration": null,
#      "captions": [{"text": "...", "start": 0, "end": 3, "style": "pain"}],
#      "narration": "..."},
#     {"source": "endcard", "duration": 2.5, "captions": [...], "narration": "..."}
#   ]
# }
# "endcard" freezes the last frame of the previous beat for `duration` seconds.
# Caption start/end are relative to the beat. Styles: "pain" (big, upper), "normal", "cta".

import json, os, shutil, subprocess, sys, glob, urllib.request

W, H, FPS = 1080, 1920, 30

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    os.path.expanduser("~/Library/Fonts/NotoSansJP-Bold.ttf"),
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)

def ffprobe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True).stdout.strip()
    return float(out)

def find_font(workdir):
    for c in ([os.environ["LUPA_FONT"]] if os.environ.get("LUPA_FONT") else []) + FONT_CANDIDATES:
        if os.path.exists(c):
            dst = os.path.join(workdir, "font" + os.path.splitext(c)[1])
            shutil.copy(c, dst)
            print("font:", c)
            return dst
    hits = glob.glob("/System/Library/Fonts/*ヒラギノ*.ttc") + glob.glob("/System/Library/Fonts/Hiragino*.ttc")
    if hits:
        dst = os.path.join(workdir, "font.ttc"); shutil.copy(hits[0], dst); print("font:", hits[0]); return dst
    raise SystemExit("No Japanese font found. Install Noto Sans JP into ~/Library/Fonts.")

def pick_voice(preferred):
    """Return ("say", voice) on macOS, ("gtts", None) when gTTS+network available, else ("espeak", None)."""
    if os.environ.get("LUPA_TTS") in ("gtts", "espeak"):
        return (os.environ["LUPA_TTS"], None)
    if shutil.which("say"):
        voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        names = [line.split()[0] for line in voices.splitlines() if line.strip()]
        for cand in [preferred, "Kyoko", "Otoya"]:
            if cand and cand in names:
                return ("say", cand)
        ja = [line.split()[0] for line in voices.splitlines() if "ja_JP" in line]
        if ja:
            return ("say", ja[0])
    try:
        import gtts  # noqa
        return ("gtts", None)
    except Exception:
        pass
    if shutil.which("espeak-ng"):
        return ("espeak", None)
    return (None, None)

def synth(text, backend, voice, out_wav):
    base = out_wav[:-4]
    if backend == "say":
        aiff = base + ".aiff"
        cmd = ["say", "-o", aiff, text]
        if voice:
            cmd[1:1] = ["-v", voice]
        run(cmd); src = aiff
    elif backend == "gtts":
        from gtts import gTTS
        mp3 = base + ".mp3"
        gTTS(text=text, lang="ja").save(mp3); src = mp3
    elif backend == "espeak":
        raw = base + "_raw.wav"
        run(["espeak-ng", "-v", "ja", "-s", "150", "-w", raw, text]); src = raw
    else:
        raise SystemExit("no TTS backend")
    run(["ffmpeg", "-y", "-i", src, "-ar", "48000", "-ac", "2", out_wav])
    return out_wav

def download(url, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst
    print("downloading", url[:80], "...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    return dst

def normalize(src, dst, duration=None):
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    cmd = ["ffmpeg", "-y", "-i", src]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst]
    run(cmd)
    return dst

def endcard_from(prev_video, dst, duration):
    png = dst + ".png"
    run(["ffmpeg", "-y", "-sseof", "-0.15", "-i", prev_video, "-frames:v", "1", "-update", "1", png])
    run(["ffmpeg", "-y", "-loop", "1", "-i", png, "-t", f"{duration:.3f}",
         "-vf", f"scale={W}:{H},setsar=1,fps={FPS},eq=brightness=-0.08",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst])
    return dst

NARRATION_SPEED = float(os.environ.get("LUPA_NARRATION_SPEED", "1.5"))  # 2026-09-11: 1.5x by default (TTS is too slow at 1.0)

def narration_clip(text, voice, target_dur, workdir, idx, speed=NARRATION_SPEED):
    backend, vname = voice
    raw = synth(text, backend, vname, os.path.join(workdir, f"nar{idx}.wav"))
    wav = os.path.join(workdir, f"nar{idx}_x{speed:.2f}.wav")
    run(["ffmpeg", "-y", "-i", raw, "-filter:a", f"atempo={speed:.3f}", wav])
    d = ffprobe_duration(wav)
    limit = max(target_dur - 0.15, 0.5)
    if d > limit:  # still too long for the beat -> squeeze a little more (max +35%)
        tempo = min(d / limit, 1.35)
        fast = os.path.join(workdir, f"nar{idx}_fast.wav")
        run(["ffmpeg", "-y", "-i", wav, "-filter:a", f"atempo={tempo:.3f}", fast])
        wav = fast
        print(f"narration {idx}: {d:.2f}s > {limit:.2f}s, extra atempo {tempo:.2f} -> {ffprobe_duration(wav):.2f}s")
    return wav

def find_bgm(job, workdir):
    """BGM source: job['bgm'] (URL or path) > assets/bgm/default.mp3 next to this repo > none."""
    src = job.get("bgm")
    if src and src.startswith("http"):
        return download(src, os.path.join(workdir, "bgm_src"))
    if src and os.path.exists(src):
        return src
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "bgm", "default.mp3")
    return default if os.path.exists(default) else None

def esc_path(p):
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

BREAK_AFTER = set("、。…？！はがもをにでとのへ・")

def wrap_jp(text, max_chars):
    """Wrap Japanese text to max_chars per line, preferring breaks after particles/punctuation."""
    def w(s):  # ASCII counts as roughly half a CJK cell
        return sum(0.55 if ord(ch) < 128 else 1.0 for ch in s)
    out = []
    for line in text.split("\n"):
        while w(line) > max_chars:
            # last index whose prefix still fits
            fit = max(i for i in range(1, len(line)) if w(line[:i]) <= max_chars)
            lo = max(1, fit // 2)
            cut = next((i for i in range(fit, lo - 1, -1) if line[i - 1] in BREAK_AFTER), fit)
            out.append(line[:cut]); line = line[cut:]
        out.append(line)
    return "\n".join(out)

def caption_filter(cap, t0, font, workdir, idx):
    style = cap.get("style", "normal")
    if style == "pain":
        size, y = 88, "h*0.14"
    elif style == "cta":
        size, y = 84, "h*0.40"
    else:
        size, y = 72, "h*0.76"
    max_chars = max(6, int((W - 160) / size))
    txt = os.path.join(workdir, f"cap{idx}.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(wrap_jp(cap["text"], max_chars))
    start, end = t0 + cap["start"], t0 + cap["end"]
    return (f"drawtext=fontfile='{esc_path(font)}':textfile='{esc_path(txt)}':"
            f"fontsize={size}:fontcolor=white:borderw=5:bordercolor=black@0.9:"
            f"box=1:boxcolor=black@0.42:boxborderw=22:line_spacing=14:"
            f"x=(w-text_w)/2:y={y}:enable='between(t,{start:.3f},{end:.3f})'")

def main():
    job_path, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    workdir = os.path.join(out_dir, "work"); os.makedirs(workdir, exist_ok=True)
    font = find_font(workdir)
    voice = pick_voice(job.get("voice"))
    print("voice:", voice)

    # 1) fetch + normalize beats
    segs = []
    for i, beat in enumerate(job["beats"]):
        norm = os.path.join(workdir, f"seg{i}.mp4")
        if beat["source"] == "endcard":
            endcard_from(segs[-1]["path"], norm, float(beat.get("duration") or 2.5))
        else:
            raw = download(beat["source"], os.path.join(workdir, f"raw{i}.mp4"))
            normalize(raw, norm, beat.get("duration"))
        segs.append({"path": norm, "dur": ffprobe_duration(norm), "beat": beat})
        print(f"beat {i}: {segs[-1]['dur']:.2f}s")

    # 2) hard-cut concat
    concat_list = os.path.join(workdir, "concat.txt")
    with open(concat_list, "w") as f:
        for s in segs:
            f.write(f"file '{s['path']}'\n")
    joined = os.path.join(workdir, "joined.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", joined])

    # 3) captions (absolute timeline) + narration per beat
    filters, audio_inputs, adelays = [], [], []
    t0, ci, prev_end = 0.0, 0, 0.0
    for i, s in enumerate(segs):
        for cap in s["beat"].get("captions", []):
            filters.append(caption_filter(cap, t0, font, workdir, ci)); ci += 1
        nar = s["beat"].get("narration")
        if nar and voice[0] is not None:
            wav = narration_clip(nar, voice, s["dur"], workdir, i)
            start = max(t0, prev_end + 0.1)   # never overlap the previous line
            audio_inputs.append(wav); adelays.append(int(start * 1000))
            prev_end = start + ffprobe_duration(wav)
        t0 += s["dur"]
    total = max(t0, prev_end) if audio_inputs else t0
    if total > t0:
        print(f"note: narration runs {total - t0:.2f}s past the video; extending last frame")

    bgm = find_bgm(job, workdir)
    bgm_gain = float(job.get("bgm_volume", os.environ.get("LUPA_BGM_VOLUME", "0.18")))  # ~-15 dB under the narration
    print("bgm:", bgm or "none")

    cmd = ["ffmpeg", "-y", "-i", joined]
    for a in audio_inputs:
        cmd += ["-i", a]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]
    vchain = [f"tpad=stop_mode=clone:stop_duration={total - t0:.3f}"] if total > t0 + 0.01 else []
    vchain += filters
    fc = "[0:v]" + (",".join(vchain) if vchain else "null") + "[v]"
    parts = []
    for k, d in enumerate(adelays):
        fc += f";[{k+1}:a]adelay={d}|{d}[a{k}]"
        parts.append(f"[a{k}]")
    if bgm:
        bi = 1 + len(audio_inputs)
        fc += (f";[{bi}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={bgm_gain:.3f},"
               f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(total-1.0,0):.3f}:d=1.0[bg]")
        parts.append("[bg]")
    has_audio = bool(parts)
    if has_audio:
        fc += f";{''.join(parts)}amix=inputs={len(parts)}:normalize=0,apad=whole_dur={total:.3f}[a]"
    final = os.path.join(out_dir, job.get("output_name", "final.mp4"))
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", final]
    run(cmd)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration,size",
                           "-of", "json", final], capture_output=True, text=True).stdout
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
        f.write(info)
    # QC frames: 4 stills (pain / demo / feature / cta) for review
    for k, t in enumerate([1.0, total * 0.35, total * 0.65, total - 1.0]):
        subprocess.run(["ffmpeg", "-y", "-ss", f"{max(t,0):.2f}", "-i", final, "-frames:v", "1", "-update", "1",
                        "-vf", "scale=360:-1", os.path.join(out_dir, f"frame{k+1}.jpg")], capture_output=True)
    print("DONE", final)

if __name__ == "__main__":
    main()
