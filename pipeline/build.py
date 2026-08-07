#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 实战短视频流水线：文案 -> 配音 -> 镜头画面 -> 合成成片。"""

import csv
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(*parts):
    return os.path.join(ROOT, *parts)


W, H, FPS = 1080, 1920, 30
FONT_TITLE = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_CAP = "/System/Library/Fonts/Hiragino Sans GB.ttc"
import os as _os

VOICE = _os.environ.get("TTS_VOICE", "Tingting")
RATE = int(_os.environ.get("TTS_RATE", "195"))
LEAD, GAP, TAIL = 0.55, 0.30, 0.95

# 每个场景的视觉元数据：配色、标题、字幕文案、运镜方向
SCENES = {
    "S1": {
        "kicker": "AI 实战 · 三步路径",
        "title": "想学 AI？",
        "title2": None,
        "num": None,
        "grad": ["0x0F0C29", "0x302B63", "0x24243E"],
        "accent": (94, 234, 213),
        "zoom": "in",
        "t1_y": 640, "t1_size": 112, "t2_y": None, "t2_size": None,
        "num_y": None, "kicker_y": 520, "bar_y": 812,
        "caps": ["想学 AI 不知从哪开始？", "三步实战路径，直接上手"],
    },
    "S2": {
        "kicker": None,
        "title": "选对场景",
        "title2": None,
        "num": "01",
        "grad": ["0x0F2027", "0x203A43", "0x2C5364"],
        "accent": (96, 165, 250),
        "zoom": "out",
        "t1_y": 650, "t1_size": 96, "t2_y": None, "t2_size": None,
        "num_y": 330, "kicker_y": None, "bar_y": 798,
        "caps": ["第一步：选对实用场景", "写周报 / 表格 / PPT"],
    },
    "S3": {
        "kicker": None,
        "title": "提问公式",
        "title2": None,
        "num": "02",
        "grad": ["0x134E5E", "0x1B6F72", "0x71B280"],
        "accent": (52, 211, 153),
        "zoom": "in",
        "t1_y": 650, "t1_size": 96, "t2_y": None, "t2_size": None,
        "num_y": 330, "kicker_y": None, "bar_y": 798,
        "caps": ["第二步：把需求说清楚", "角色 + 任务 + 细节 + 要求"],
    },
    "S4": {
        "kicker": None,
        "title": "沉淀模板",
        "title2": None,
        "num": "03",
        "grad": ["0x1A1A2E", "0x16213E", "0x533483"],
        "accent": (167, 139, 250),
        "zoom": "out",
        "t1_y": 650, "t1_size": 96, "t2_y": None, "t2_size": None,
        "num_y": 330, "kicker_y": None, "bar_y": 798,
        "caps": ["第三步：固定工作流", "沉淀成你的 AI 模板库"],
    },
    "S5": {
        "kicker": None,
        "title": "AI 不是学出来的",
        "title2": "是用出来的",
        "num": None,
        "grad": ["0x2B1055", "0x41295A", "0x3A1C71"],
        "accent": (251, 191, 36),
        "zoom": "in",
        "t1_y": 580, "t1_size": 92, "t2_y": 700, "t2_size": 92,
        "num_y": None, "kicker_y": None, "bar_y": 846,
        "caps": ["不是学出来的，是用出来的", "关注我，每天一个 AI 实战技巧"],
    },
}


def sh(*args):
    subprocess.run(list(args), check=True)


def probe_dur(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path]
    )
    return float(out.strip())


def parse_voiceover():
    scenes, order, cur = {}, [], None
    with open(P("copy", "voiceover.txt"), encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                sid = line[1:].strip().split()[0]
                cur = sid
                order.append(sid)
                scenes[sid] = {"lines": []}
            else:
                scenes[cur]["lines"].append(line)
    return scenes, order


def generate_speech(scenes, order):
    os.makedirs(P("audio", "short", "tmp"), exist_ok=True)
    durs = {}
    for sid in order:
        for i, txt in enumerate(scenes[sid]["lines"]):
            stem = f"{sid}_{i}"
            aiff = P("audio", "short", "tmp", stem + ".aiff")
            wav = P("audio", "short", "tmp", stem + ".wav")
            sh("say", "-v", VOICE, "-r", str(RATE), "-o", aiff, txt)
            sh("ffmpeg", "-y", "-i", aiff, "-ar", "44100", "-ac", "1", wav)
            durs[(sid, i)] = probe_dur(wav)
    return durs


def compute_timings(scenes, order, durs):
    timings = {}
    for sid in order:
        lines = scenes[sid]["lines"]
        starts, acc = [], LEAD
        for i in range(len(lines)):
            starts.append(acc)
            acc += durs[(sid, i)] + (GAP if i < len(lines) - 1 else 0)
        scene_dur = acc + TAIL
        timings[sid] = {"starts": starts, "dur": scene_dur}
    return timings


def make_backgrounds(order):
    os.makedirs(P("assets", "short"), exist_ok=True)
    for sid in order:
        ai_path = P("assets", "ai", f"bg_{sid}.png")
        if os.path.exists(ai_path):
            # 有 AI 生成的底图时优先使用，缩放到 2 倍分辨率以便运镜推拉
            sh("ffmpeg", "-y", "-i", ai_path,
               "-vf", f"scale={2*W}:{2*H}:flags=lanczos",
               "-frames:v", "1", P("assets", "short", f"bg_{sid}.png"))
            continue
        meta = SCENES[sid]
        c0, c1, c2 = meta["grad"]
        sh("ffmpeg", "-y",
           "-f", "lavfi",
           "-i", f"gradients=s={2*W}x{2*H}:c0={c0}:c1={c1}:c2={c2}"
                 f":nb_colors=3:type=linear:speed=0",
           "-frames:v", "1", P("assets", "short", f"bg_{sid}.png"))


def make_text_layers(order):
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(P("assets", "short", "txt"), exist_ok=True)

    def font(path, size):
        return ImageFont.truetype(path, size)

    for idx, sid in enumerate(order):
        meta = SCENES[sid]
        accent = meta["accent"] + (255,)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        if meta["num_y"]:
            f = font(FONT_TITLE, 190)
            d.text((W / 2, meta["num_y"]), meta["num"], font=f,
                   fill=(255, 255, 255, 26), anchor="mm")
        if meta["kicker_y"]:
            f = font(FONT_TITLE, 44)
            d.text((W / 2, meta["kicker_y"]), meta["kicker"], font=f,
                   fill=accent, anchor="mm")
        f1 = font(FONT_TITLE, meta["t1_size"])
        d.text((W / 2 + 3, meta["t1_y"] + 6), meta["title"], font=f1,
               fill=(0, 0, 0, 90), anchor="mm")
        d.text((W / 2, meta["t1_y"]), meta["title"], font=f1,
               fill=(255, 255, 255, 255), anchor="mm")
        if meta["t2_y"]:
            f2 = font(FONT_TITLE, meta["t2_size"])
            d.text((W / 2, meta["t2_y"]), meta["title2"], font=f2,
                   fill=accent, anchor="mm")
        d.rounded_rectangle(
            (W / 2 - 160, meta["bar_y"], W / 2 + 160, meta["bar_y"] + 6),
            radius=3, fill=accent)

        for k in range(5):
            x0 = W / 2 - 104 + k * 52
            fill = accent if k == idx else (255, 255, 255, 70)
            d.rounded_rectangle((x0, 1780, x0 + 22, 1780 + 22),
                                radius=7, fill=fill)
        img.save(P("assets", "short", f"layer_{sid}.png"))

        for i, cap in enumerate(meta["caps"]):
            f = font(FONT_CAP, 46)
            bbox = d.textbbox((0, 0), cap, font=f)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pw, ph = tw + 96, th + 52
            pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            pd = ImageDraw.Draw(pill)
            pd.rounded_rectangle((0, 0, pw, ph), radius=ph // 2,
                                 fill=(0, 0, 0, 115))
            pd.text((pw / 2, ph / 2), cap, font=f, fill=(255, 255, 255, 255),
                    anchor="mm")
            pill.save(P("assets", "short", "txt", f"cap_{sid}_{i}.png"))


def make_scene_audio(sid, lines, durs, timings):
    tmp = P("audio", "short", "tmp")
    segs = []

    def silence(dur, name):
        path = os.path.join(tmp, name)
        sh("ffmpeg", "-y", "-f", "lavfi", "-i",
           f"anullsrc=r=44100:cl=mono", "-t", f"{dur:.3f}",
           "-c:a", "pcm_s16le", path)
        return path

    segs.append(silence(LEAD, f"{sid}_sil0.wav"))
    for i, txt in enumerate(lines):
        segs.append(P("audio", "short", "tmp", f"{sid}_{i}.wav"))
        if i < len(lines) - 1:
            segs.append(silence(GAP, f"{sid}_gap{i}.wav"))
    segs.append(silence(TAIL, f"{sid}_tail.wav"))

    lst = os.path.join(tmp, f"{sid}_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in segs:
            f.write(f"file '{os.path.abspath(p)}'\n")
    scene_wav = P("audio", "short", f"scene_{sid}.wav")
    sh("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:a", "pcm_s16le", scene_wav)
    return scene_wav


def render_scenes(order, lines_map, durs, timings):
    os.makedirs(P("output", "short"), exist_ok=True)
    for sid in order:
        meta = SCENES[sid]
        dur = timings[sid]["dur"]
        zoom = ("min(1+0.0012*on,1.22)" if meta["zoom"] == "in"
                else "max(1.22-0.0012*on,1.00)")
        fc = [
            f"[0:v]scale={2*W}:{2*H},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS},format=yuv420p[bg]",
            "[bg][1:v]overlay=0:0[o0]",
        ]
        for i, cap in enumerate(meta["caps"]):
            s = timings[sid]["starts"][i] + 0.05
            e = s + durs[(sid, i)] - 0.05
            fc.append(
                f"[o{i}][{i + 2}:v]overlay=0:1380:enable='between(t,{s:.2f},{e:.2f})'[o{i + 1}]"
            )
        fc.append(f"[o{len(meta['caps'])}]"
                  f"fade=t=in:st=0:d=0.4,"
                  f"fade=t=out:st={dur - 0.45:.2f}:d=0.45[v]")

        cmd = ["ffmpeg", "-y",
               "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}",
               "-i", P("assets", "short", f"bg_{sid}.png"),
               "-loop", "1", "-framerate", str(FPS),
               "-i", P("assets", "short", f"layer_{sid}.png")]
        for i in range(len(meta["caps"])):
            cmd += ["-loop", "1", "-framerate", str(FPS),
                    "-i", P("assets", "short", "txt", f"cap_{sid}_{i}.png")]
        wav = make_scene_audio(sid, lines_map[sid]["lines"], durs, timings)
        cmd += ["-i", wav, "-filter_complex", ";".join(fc), "-map", "[v]",
                "-map", f"{len(meta['caps']) + 2}:a",
                "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-ar", "44100", "-ac", "1", "-r", str(FPS),
                "-t", f"{dur:.3f}", P("output", "short", f"scene_{sid}.mp4")]
        sh(*cmd)


def concat_scenes(order):
    lst = P("audio", "short", "tmp", "scenes.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for sid in order:
            f.write(f"file '{os.path.abspath(P('output', 'short', f'scene_{sid}.mp4'))}'\n")
    out = P("output", "short", "concat.mp4")
    sh("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
       "-c", "copy", out)
    return out


def make_music(total):
    a = ("sin(2*PI*220*t)+sin(2*PI*277.18*t)+sin(2*PI*329.63*t)")
    f = ("sin(2*PI*174.61*t)+sin(2*PI*220*t)+sin(2*PI*261.63*t)")
    expr = (f"0.045*(0.7+0.3*sin(2*PI*0.11*t))*"
            f"(if(lt(mod(t,16),8),{a},{f}))")
    sh("ffmpeg", "-y", "-f", "lavfi",
       "-i", f"aevalsrc=exprs='{expr}':s=44100:d={total:.2f}",
       "-af", f"lowpass=f=900,afade=t=in:st=0:d=1.5,"
              f"afade=t=out:st={total - 2.0:.2f}:d=2",
       "-ac", "1", P("audio", "short", "music.wav"))


def finalize(concat, total):
    out = P("output", "short", "ai_3steps_demo.mp4")
    sh("ffmpeg", "-y", "-i", concat, "-i", P("audio", "short", "music.wav"),
       "-filter_complex",
       "[0:a]volume=1.0[a0];"
       "[1:a]volume=0.35,lowpass=f=850[m];"
       "[a0][m]amix=inputs=2:duration=first:dropout_transition=0,"
       "aformat=sample_rates=44100:channel_layouts=stereo[a]",
       "-map", "0:v", "-map", "[a]", "-c:v", "copy",
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    return out


def preview_frames(total):
    outdir = P("output", "preview")
    os.makedirs(outdir, exist_ok=True)
    n = 8
    for k in range(n):
        t = total * (k + 0.5) / n
        sh("ffmpeg", "-y", "-ss", f"{t:.2f}",
           "-i", P("output", "short", "ai_3steps_demo.mp4"),
           "-frames:v", "1", "-vf", "scale=540:960",
           os.path.join(outdir, f"f{k:02d}.jpg"))


def write_reports(scenes, order, durs, timings, total):
    rows = []
    for sid in order:
        meta = SCENES[sid]
        rows.append({
            "场次": sid,
            "画面": meta["title"] if not meta["num"] else meta["num"] + " " + meta["title"],
            "口播文案": " / ".join(scenes[sid]["lines"]),
            "字幕文案": " / ".join(meta["caps"]),
            "时长(秒)": round(timings[sid]["dur"], 2),
        })
    with open(P("script", "storyboard.csv"), "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "voice": VOICE, "rate": RATE,
        "total_duration": round(total, 2),
        "scenes": [
            {
                "id": sid,
                "dur": round(timings[sid]["dur"], 2),
                "lines": [
                    {"text": scenes[sid]["lines"][i],
                     "start": round(timings[sid]["starts"][i], 2),
                     "dur": round(durs[(sid, i)], 2)}
                    for i in range(len(scenes[sid]["lines"]))
                ],
            }
            for sid in order
        ],
    }
    with open(P("output", "short", "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main():
    scenes, order = parse_voiceover()
    durs = generate_speech(scenes, order)
    timings = compute_timings(scenes, order, durs)
    make_backgrounds(order)
    make_text_layers(order)
    render_scenes(order, scenes, durs, timings)
    concat = concat_scenes(order)
    total = probe_dur(concat)
    make_music(total)
    out = finalize(concat, total)
    preview_frames(total)
    write_reports(scenes, order, durs, timings, total)
    print("DONE", out, "duration", round(total, 2))


if __name__ == "__main__":
    main()
