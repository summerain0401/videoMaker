#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频公共生产引擎：语义分镜 + Azure 配音 + 字幕/SFX/BGM/渲染。

项目制路径：默认渲染 projects/001_金钱的艺术（环境变量 PROJECT 可换项目），
文案/分镜在项目 input/，画面在项目 assets/，配音缓存与背景乐在项目 audio/，
成片与报告输出到项目 output/。

用法：
  python3 pipeline/build_long.py            # 全片渲染（PROJECT=001）
  PROJECT=002 python3 pipeline/build_long.py --pilot
  python3 pipeline/build_long.py --project 001 --blocks 0,1,2

环境变量：
  PROJECT=001              项目 id（默认 001；--project 参数可覆盖）
  AZURE_SPEECH_KEY/REGION  Azure 凭据；音色从 project.json/run 快照读取
  在项目 audio/ 放入用户音乐文件（music.wav/mp3/m4a…）自动混音，否则纯人声
"""

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj as PJ
import long_visuals as V

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(*parts):
    return os.path.join(ROOT, *parts)


def PROJ(*parts):
    """当前项目内路径（input/assets/audio/output）。"""
    return PJ.PROJ(*parts)


W, H, FPS = 1920, 1080, 30
KENZOOM = 0.08  # 每镜头 Ken Burns 统一缓推幅度（1.0→1.08，常量可调）
LEAD, TAIL = 0.4, 0.6
QUOTE_LEAD = 1.0
PHASE_DUR = 4.0
XD = 0.3  # 块间转场时长（方向型快速转场，不用 dissolve 家族）
NO_TTS = False  # --no-tts：跳过配音合成，音轨静音
RUN_AZURE_VOICE = None  # workflow run 的 provider 快照；非用户可选项
BOOK = "《金钱的艺术》"
AUTHOR = "Morgan Housel"


def story_path():
    """当前项目唯一语义分镜路径（--project 覆盖后需动态解析）。"""
    return PROJ("input", "storyboard.json")

PALETTES = {
    "TITLE": ["0x2B2436", "0x3D3152", "0x574B79"],
    "01": ["0x232230", "0x35324A", "0x4A4563"],
    "02": ["0x241F1B", "0x3A3127", "0x554735"],
    "03": ["0x1E2A2A", "0x2E3E3E", "0x475A56"],
    "04": ["0x22263A", "0x333A5C", "0x4A5580"],
    "05": ["0x2A1F2E", "0x3E2B45", "0x5A3D63"],
}
PARCHMENT = ["0xF4EBDC", "0xEADFC6", "0xDCCBAA"]


def sh(*args):
    subprocess.run(list(args), check=True)


def probe_dur(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path])
    return float(out.strip())


def parse_script():
    blocks, cur = [], None
    with open(PROJ("input", "script.txt"), encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("# "):
                head = line[2:].strip()
                cur = {"type": head.split()[0], "head": head,
                       "lines": [], "voice": None, "phase": None,
                       "author": None}
                blocks.append(cur)
            elif line.startswith("## "):
                cur["lines"].append(line[3:].strip())
            elif line.startswith("voice："):
                cur["voice"] = line[len("voice："):].strip()
            elif line.startswith("author："):
                cur["author"] = line[len("author："):].strip()
    cur_phase = None
    for b in blocks:
        if b["type"] == "PHASE":
            cur_phase = b["head"]
        b["phase"] = cur_phase
    return blocks


def phase_num(phase_head):
    """阶段头 'PHASE 01 · 开场共情' -> '01'。"""
    parts = (phase_head or "").split()
    if len(parts) >= 2 and parts[0] == "PHASE":
        return parts[1]
    return parts[0] if parts else ""


def phase_name(phase_head):
    """阶段头 -> '开场共情'。"""
    num = phase_num(phase_head)
    if num and phase_head and num in phase_head:
        return phase_head.split(num, 1)[1].strip(" ·")
    return phase_head or ""


def book_meta(blocks):
    """从 TITLE 块提取书名/钩子/作者（缺失回退常量）。"""
    book, hook, author = BOOK, None, AUTHOR
    for b in blocks:
        if b["type"] == "TITLE":
            author = b.get("author") or AUTHOR
            if b["lines"]:
                book = b["lines"][0]
            if len(b["lines"]) > 1:
                hook = b["lines"][1]
            break
    return book, hook, author


def azure_voice():
    """从 run 快照或项目配置读取正式音色；不接受环境变量覆盖。"""
    if RUN_AZURE_VOICE:
        return RUN_AZURE_VOICE
    speech = PJ.read_meta().get("providers", {}).get("speech", {})
    if speech.get("name") != "azure":
        raise RuntimeError("project.json 的 providers.speech.name 必须为 azure")
    voice = speech.get("voice")
    if not isinstance(voice, str) or not voice.strip():
        raise RuntimeError("project.json 缺少 providers.speech.voice")
    return voice.strip()


def synth_line(text, wav):
    import tts_azure
    tts_azure.synthesize(text, wav, voice=azure_voice())


def voice_stem(idx, text=""):
    cfg = "azure" + "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in azure_voice())
    h = hashlib.md5((text or "").encode("utf-8")).hexdigest()[:8]
    return f"blk{idx:02d}_{cfg}_{h}"


def make_audio(blocks):
    os.makedirs(PROJ("audio", "voice"), exist_ok=True)
    os.makedirs(PROJ("audio", "tmp"), exist_ok=True)
    for i, b in enumerate(blocks):
        source_idx = b.get("_source_idx", i)
        if b["voice"]:
            stem = voice_stem(source_idx, b["voice"])
            raw = PROJ("audio", "voice", stem + "_raw.wav")
            pp = PROJ("audio", "voice", stem + ".wav")
            if not (os.path.exists(raw) and os.path.exists(pp)):
                synth_line(b["voice"], raw)
                # 语音后处理：高通 + 轻压限 + 逐段响度对齐
                sh("ffmpeg", "-y", "-i", raw, "-af",
                   "highpass=f=80,acompressor=threshold=-18dB:ratio=2.5:"
                   "attack=6:release=150,loudnorm=I=-16:TP=-1.5:LRA=11",
                   "-ar", "44100", "-ac", "1", pp)
            b["voice_dur"] = probe_dur(pp)
            expect = len(b["voice"]) / 4.0
            if b["voice_dur"] < min(1.0, expect / 2):
                raise RuntimeError(
                    f"语音合成异常：段落 {i} {len(b['voice'])} 字仅 "
                    f"{b['voice_dur']:.2f}s，检查 TTS 配置")
            b["dur"] = b["voice_dur"]
        else:
            b["voice_dur"] = 0.0
            b["dur"] = PHASE_DUR
    return blocks


def scene_lead(b):
    return QUOTE_LEAD if b["type"] == "QUOTE" else LEAD


def scene_time(b):
    if b["type"] == "PHASE":
        return PHASE_DUR
    return scene_lead(b) + b["voice_dur"] + TAIL


def palette_for(b):
    if b["type"] == "QUOTE":
        return PARCHMENT
    if b["type"] == "TITLE":
        return PALETTES["TITLE"]
    key = phase_num(b["phase"]) or "01"
    return PALETTES.get(key, PALETTES["01"])


def motion_exprs(idx, nframes):
    """统一 1.0→1+KENZOOM 缓推：锚点上移(50%,35%)对准面部 + X 轴 2.5% 缓移 + ease-out。

    缩放与平移都用 ease-out（1-(1-p)²），切入前 0.5s 明显动态入场、随后缓推；
    X 向平移 2.5% 在缩放余量内，不露画面边缘。
    """
    n = max(nframes, 1)
    p = f"(1-pow(1-min(1,on/{n}),2))"
    z = f"1+{KENZOOM}*({p})"
    cx = f"'(iw-iw/zoom)*0.5+iw*0.025*({p})'"
    cy = f"'(ih-ih/zoom)*0.35'"
    return z, cx, cy


def load_storyboard():
    """读取唯一、已提升的语义分镜。"""
    if not os.path.exists(story_path()):
        raise FileNotFoundError(f"缺少正式语义分镜：{story_path()}")
    with open(story_path(), encoding="utf-8") as f:
        return json.load(f)


def phase_art_path(blocks, idx):
    """阶段页背景：后续第一个有卡点图的内容块首拍画面（保持故事连续）。"""
    for j in range(idx + 1, len(blocks)):
        source_idx = blocks[j].get("_source_idx", j)
        p = PROJ("assets", "scenes", f"{source_idx:02d}_0.png")
        if os.path.exists(p):
            return p
    return None


def beat_art_path(b, idx, beat_idx, blocks=None):
    """卡点画面：优先 scenes/{idx}_{beat}.png；PHASE 用后续内容块首拍；否则 None。"""
    source_idx = b.get("_source_idx", idx)
    p = PROJ("assets", "scenes", f"{source_idx:02d}_{beat_idx}.png")
    if os.path.exists(p):
        return p
    if b["type"] == "PHASE" and blocks is not None:
        return phase_art_path(blocks, idx)
    return None


def make_beat_bg(b, idx, beat_idx, art_path):
    """卡点底图：原图直接放大（不压暗），否则程序化底图。"""
    out = PROJ("assets", "layers", f"nbg_{idx:02d}_{beat_idx:02d}.png")
    if art_path and os.path.exists(art_path):
        Image.open(art_path).convert("RGB").resize(
            (2 * W, 2 * H), Image.LANCZOS).save(out)
    else:
        c0, c1, c2 = palette_for(b)
        V.procedural_bg(c0, c1, c2, 2 * W, 2 * H).save(out)
    return out


def beat_durations(sdur, beats):
    """按字符占比分配每拍时长（硬切无重叠，总长 = sdur）。"""
    n = len(beats)
    if n <= 1:
        return [sdur]
    weights = [max(1, be["end_char"] - be["start_char"]) for be in beats]
    return [sdur * w / sum(weights) for w in weights]


def subtitle_windows(block, sub):
    """字幕句子在块内的时间窗（按字符比例估算）。"""
    vd = block["voice_dur"]
    chars = max(len(block["voice"] or ""), 1)
    lead = scene_lead(block)
    s = lead + (sub["start_char"] / chars) * vd
    e = lead + (sub["end_char"] / chars) * vd
    return s, e


CLAUSE_PUNCT = "，。！？、；：…—"
LEAD_PUNCT = "，。！？、；：…—"

try:
    import jieba
    _HAS_JIEBA = True
except Exception:
    _HAS_JIEBA = False

PROTECTED_WORDS = [
    "思维框架", "年薪百万", "金钱心理学", "金钱的艺术", "工资到账",
    "底层病灶", "核心模型", "实战工具", "哲学升华", "认知差",
    "存钱陷阱", "复利曲线", "存款数字", "跟钱的关系", "空虚感",
    "越花钱", "越省钱", "挣得不多", "掏不出", "一夜暴富",
    "跳槽加薪", "年终奖",
]
if _HAS_JIEBA:
    for _w in PROTECTED_WORDS:
        jieba.add_word(_w)
    try:
        jieba.initialize()
    except Exception:
        pass


def _pieces_from_tokens(tokens, max_chars):
    """按 jieba 词元累积成 ≤max_chars 的段，标点并入前段。"""
    pieces, cur = [], ""
    for tok in tokens:
        if not tok.strip():
            continue
        if tok in CLAUSE_PUNCT and cur:
            cur += tok
            continue
        if cur and len(cur) + len(tok) > max_chars:
            pieces.append(cur)
            cur = tok
        else:
            cur += tok
    if cur:
        pieces.append(cur)
    return pieces


def _char_split(cl, max_chars):
    """无 jieba 时按字切分，切后剩余段 ≥3 字。"""
    i, out = 0, []
    while len(cl) - i > max_chars:
        cut = i + max_chars
        while len(cl) - cut < 3 and cut > i:
            cut -= 1
        out.append(cl[i:cut])
        i = cut
    out.append(cl[i:])
    return out


def split_subtitle_chunks(text, max_chars=15):
    """字幕分块：按标点切子句 → jieba 分词 → 累积 ≤max_chars 字/屏。

    规则：固定词组（思维框架/年薪百万/真相）严禁跨屏切断；事件不以标点或
    单字开头；jieba 缺失时回退子句按字切分。
    """
    clauses, cur = [], ""
    for ch in text:
        cur += ch
        if ch in CLAUSE_PUNCT:
            clauses.append(cur)
            cur = ""
    if cur:
        clauses.append(cur)
    # 超长子句按词切（jieba），避免切碎固定词组
    units = []
    for cl in clauses:
        if len(cl) <= max_chars:
            units.append(cl)
            continue
        if _HAS_JIEBA:
            units.extend(_pieces_from_tokens(list(jieba.cut(cl)), max_chars))
        else:
            units.extend(_char_split(cl, max_chars))
    # 累积到 ≤max_chars 的屏
    out, buf = [], ""
    for u in units:
        if buf and len(buf) + len(u) <= max_chars:
            buf += u
        else:
            if buf:
                out.append(buf)
            buf = u
    if buf:
        out.append(buf)
    # 行首标点并入上一屏
    fixed = []
    for s in out:
        while s and s[0] in LEAD_PUNCT and fixed:
            fixed[-1] += s[0]
            s = s[1:]
        if s:
            fixed.append(s)
    # 单字屏兜底并入上一屏
    merged = []
    for s in fixed:
        if len(s) == 1 and merged:
            merged[-1] += s
        else:
            merged.append(s)
    return merged


def render_scene_narrative(blocks, idx, total, first, last, meta, story):
    """叙事模式：卡点画面 zoompan 硬切拼接 + 字幕叠层。"""
    b = blocks[idx]
    sdur = scene_time(b)
    source_idx = b.get("_source_idx", idx)
    sb_map = {item["block_idx"]: item for item in story["blocks"]}
    sb = sb_map[source_idx]
    beats = sb["beats"]
    durs = beat_durations(sdur, beats)
    n = len(beats)
    bg_paths = []
    for beat in beats:
        beat_idx = beat["beat_idx"]
        bg_paths.append(make_beat_bg(
            b, idx, beat_idx, beat_art_path(b, idx, beat_idx, blocks)))
    deco = PROJ("assets", "layers", f"deco_{idx:02d}.png")
    V.make_deco_layer(idx).save(deco)
    sub_events = []
    pop_events = []
    for s in sb["subtitles"]:
        ts, te = subtitle_windows(b, s)
        total = max(s["end_char"] - s["start_char"], 1)
        offset = 0
        for ch in split_subtitle_chunks(s["text"]):
            ln = len(ch)
            st = ts + (offset / total) * (te - ts)
            et = ts + ((offset + ln) / total) * (te - ts)
            p = PROJ("assets", "layers",
                  f"sub_{idx:02d}_{s['id']:02d}_{offset:03d}.png")
            V.make_subtitle_layer(ch).save(p)
            sub_events.append((p, st, et))
            hl = V.first_highlight_span(ch)
            if hl:
                hp = PROJ("assets", "layers",
                          f"subpop_{idx:02d}_{s['id']:02d}_{offset:03d}.png")
                himg, hcx, hcy = V.make_subtitle_highlight_layer(ch)
                himg.save(hp)
                frac = hl[0] / max(ln, 1)
                pt = st + frac * (et - st)
                pop_events.append((hp, pt, hcx, hcy))
            offset += ln

    fc = []
    for k in range(n):
        nframes = max(int(durs[k] * FPS), 1)
        z, cx, cy = motion_exprs(idx * 5 + k, nframes)
        fc.append(
            f"[{k}:v]scale={2 * W}:{2 * H},"
            f"zoompan=z='{z}':x={cx}:y={cy}:d={nframes}:"
            f"s={W}x{H}:fps={FPS},"
            f"format=yuv420p[b{k}]"
        )
    # 块内卡点硬切：各拍 zoompan 后 concat 拼接（保留 Ken Burns，无叠化）
    if n > 1:
        fc.append("".join(f"[b{k}]" for k in range(n)) +
                  f"concat=n={n}:v=1:a=0[bc]")
        o_prev = "bc"
    else:
        o_prev = "b0"
    bi = n
    # deco 光斑视差层（相对卡点画面漂移，制造纵深）
    fc.append(f"[{o_prev}][{bi}:v]overlay=x='34*sin(t/4)':"
              f"y='22*cos(t/3.5)'[d0]")
    o_prev = "d0"
    bi += 1
    # 底部半透明渐变遮罩（画面之上、字幕之下，保证字幕可读）
    grad = PROJ("assets", "layers", f"grad_{idx:02d}.png")
    V.make_bottom_gradient().save(grad)
    fc.append(f"[{o_prev}][{bi}:v]overlay=0:0[g0]")
    o_prev = "g0"
    bi += 1
    for k, (p, ts, te) in enumerate(sub_events):
        fc.append(
            f"[{bi}:v]fade=t=in:st={ts:.2f}:d=0.12:alpha=1,"
            f"format=rgba[S{k}]"
        )
        fc.append(
            f"[{o_prev}][S{k}]overlay=0:0:"
            f"enable='between(t,{ts:.2f},{te:.2f})'[o{k + 3}]"
        )
        o_prev = f"o{k + 3}"
        bi += 1
    for k, (hp, pt, hcx, hcy) in enumerate(pop_events):
        fc.append(
            f"[{bi}:v]zoompan=z='1+0.1*sin(PI*min(1,on/9))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=10:s={W}x{H}:fps={FPS},format=rgba,"
            f"setpts=PTS+{pt:.3f}/TB[PP{k}]"
        )
        fc.append(
            f"[{o_prev}][PP{k}]overlay=x='{hcx - W / 2}':"
            f"y='{hcy - H / 2}':"
            f"enable='between(t,{pt:.2f},{pt + 0.35:.2f})'[o{bi}]"
        )
        o_prev = f"o{bi}"
        bi += 1
    tail = f"[{o_prev}]vignette=PI/7"
    if first:
        tail += ",fade=t=in:st=0:d=0.5"
    if last:
        tail += f",fade=t=out:st={sdur - 0.5:.2f}:d=0.5"
    fc.append(tail + ",format=yuv420p[v]")

    sfx_events = find_sfx(b["voice"], b["voice_dur"])
    wav = make_scene_audio(b, idx, sfx_events)
    cmd = ["ffmpeg", "-y"]
    for k in range(n):
        cmd += ["-i", bg_paths[k]]
    cmd += ["-loop", "1", "-framerate", str(FPS),
            "-t", f"{sdur:.3f}", "-i", deco]
    cmd += ["-loop", "1", "-framerate", str(FPS),
            "-t", f"{sdur:.3f}", "-i", grad]
    for p, ts, te in sub_events:
        cmd += ["-loop", "1", "-framerate", str(FPS),
                "-t", f"{sdur:.3f}", "-i", p]
    for hp, pt, hcx, hcy in pop_events:
        cmd += ["-i", hp]
    cmd += ["-i", wav, "-filter_complex", ";".join(fc),
            "-map", "[v]", "-map", f"{bi}:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-ar", "44100", "-ac", "1", "-r", str(FPS),
            "-t", f"{sdur:.3f}", PROJ("output", f"vs2_{idx:02d}.mp4")]
    sh(*cmd)


def render_frames_narrative(blocks, meta, story):
    """叙事模式快速抽帧：每拍 2 张静态帧（无字幕/带字幕），PIL 合成。"""
    outdir = PROJ("output", "preview")
    os.makedirs(outdir, exist_ok=True)
    for i, b in enumerate(blocks):
        source_idx = b.get("_source_idx", i)
        sb_map = {item["block_idx"]: item for item in story["blocks"]}
        sb = sb_map[source_idx]
        for be in sb["beats"]:
            beat_idx = be["beat_idx"]
            art = beat_art_path(b, i, beat_idx, blocks)
            if art and os.path.exists(art):
                img = Image.open(art).convert("RGB")
            else:
                c0, c1, c2 = palette_for(b)
                img = V.procedural_bg(c0, c1, c2, W, H)
            img = img.resize((int(W * 1.06), int(H * 1.06)), Image.LANCZOS)
            x0 = (img.width - W) // 2
            y0 = (img.height - H) // 2
            img = img.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")
            img.convert("RGB").save(
                os.path.join(outdir,
                             f"m3n_{source_idx:02d}_{beat_idx:02d}.jpg"),
                quality=88)
            if sb["subtitles"]:
                img2 = Image.alpha_composite(
                    img, V.make_subtitle_layer(
                        split_subtitle_chunks(
                            sb["subtitles"][0]["text"])[0]))
                img2.convert("RGB").save(
                    os.path.join(
                        outdir,
                        f"m3n_{source_idx:02d}_{beat_idx:02d}_s.jpg"),
                    quality=88)
        print(f"nframe {source_idx:02d} {b['type']} done")


SFX_KEYWORDS = {
    "coin": ["工资到账", "到账", "存钱", "入账", "存款到账"],
    "calc": ["打车", "算账", "计算器", "账单", "按键", "按着"],
    "reveal": ["真相", "揭示", "撕开", "原来", "关键"],
}
SFX_ENABLED = os.environ.get("SFX", "1") != "0"
SFX_MAX_PER_KIND = 3


def synth_sfx(kind):
    """用 ffmpeg lavfi 合成短音效（缓存到项目 audio/tmp/）。"""
    tmp = PROJ("audio", "tmp")
    os.makedirs(tmp, exist_ok=True)
    out = os.path.join(tmp, f"sfx_{kind}.wav")
    if os.path.exists(out):
        return out
    if kind == "coin":
        expr = ("0.6*sin(2*PI*(880+880*t/0.35)*t)*exp(-7*t)")
        sh("ffmpeg", "-y", "-f", "lavfi",
           "-i", f"aevalsrc={expr}:s=44100:d=0.35",
           "-c:a", "pcm_s16le", out)
    elif kind == "reveal":
        sh("ffmpeg", "-y", "-f", "lavfi",
           "-i", "aevalsrc=0.55*sin(2*PI*(180-125*t/0.3)*t)*exp(-6*t):"
                "s=44100:d=0.3",
           "-c:a", "pcm_s16le", out)
    else:  # calc：单个 1kHz 短 click
        sh("ffmpeg", "-y", "-f", "lavfi",
           "-i", "aevalsrc=0.5*sin(2*PI*1000*t)*exp(-60*t):"
                "s=44100:d=0.08",
           "-c:a", "pcm_s16le", out)
    return out


def find_sfx(voice, vd):
    """按关键词在口播中的字符偏移映射到块内时间（毫秒）。"""
    events = []
    if not SFX_ENABLED or not voice:
        return events
    n = max(len(voice), 1)
    last_time = {}
    for kind, words in SFX_KEYWORDS.items():
        hits = 0
        for w in words:
            i = voice.find(w)
            while i != -1 and hits < SFX_MAX_PER_KIND:
                ms = int((LEAD + i / n * vd) * 1000)
                if ms - last_time.get(kind, -10000) >= 600:
                    events.append((kind, ms))
                    last_time[kind] = ms
                    hits += 1
                i = voice.find(w, i + len(w))
    return events


def mix_sfx(block_wav, events, out):
    """把 SFX 按时间点混入块配音（adelay + volume 0.35 + amix）。"""
    inputs = ["-i", block_wav]
    fc, amix_in = [], ["[0:a]"]
    in_idx = 1
    for i, (kind, ms) in enumerate(events):
        sfx = synth_sfx(kind)
        inputs += ["-i", sfx]
        delays = [ms] if kind == "coin" else [ms, ms + 120, ms + 240]
        for j, d in enumerate(delays):
            lab = f"s{i}_{j}"
            fc.append(f"[{in_idx}:a]adelay={d}|{d},volume=0.35[{lab}]")
            amix_in.append(f"[{lab}]")
        in_idx += 1
    fc.append("".join(amix_in) +
              f"amix=inputs={len(amix_in)}:duration=first:"
              f"dropout_transition=0,alimiter[a]")
    sh("ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
       "-map", "[a]", "-ar", "44100", "-ac", "1", out)
    return out


def make_scene_audio(b, idx, sfx_events=None):
    tmp = PROJ("audio", "tmp")
    os.makedirs(tmp, exist_ok=True)
    if NO_TTS or b["type"] == "PHASE":
        out = os.path.join(tmp, f"vs2_{idx:02d}.wav")
        sh("ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
           "-t", f"{scene_time(b):.3f}", "-c:a", "pcm_s16le", out)
        return out
    segs = []

    def silence(dur, name):
        path = os.path.join(tmp, name)
        sh("ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
           "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", path)
        return path

    segs.append(silence(scene_lead(b), f"vs2_{idx:02d}_lead.wav"))
    source_idx = b.get("_source_idx", idx)
    segs.append(PROJ("audio", "voice",
                  voice_stem(source_idx, b["voice"]) + ".wav"))
    segs.append(silence(TAIL, f"vs2_{idx:02d}_tail.wav"))
    lst = os.path.join(tmp, f"vs2_{idx:02d}_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in segs:
            f.write(f"file '{os.path.abspath(p)}'\n")
    out = PROJ("audio", "tmp", f"vs2_{idx:02d}.wav")
    sh("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:a", "pcm_s16le", out)
    if sfx_events:
        out = mix_sfx(out, sfx_events,
                      PROJ("audio", "tmp", f"vs2_{idx:02d}_sfx.wav"))
    return out


def find_music(seg=None):
    """按段查找背景乐：优先 music_seg{N}.{ext}，缺失回退 music.wav。"""
    for ext in ("mp3", "wav", "m4a", "flac", "aac"):
        if seg:
            p = PROJ("audio", f"music_seg{seg}.{ext}")
            if os.path.exists(p):
                return p
        for name in (f"user_music.{ext}", f"music.{ext}"):
            p = PROJ("audio", name)
            if os.path.exists(p):
                return p
    return None


def compute_segments(blocks, story):
    """按拍 segment（hook/insight/action）计算三段时间区间（最终时间轴）。
    返回 [seg1_start, seg2_start, seg3_start, total]；无标签拍继承前段。"""
    durs = [scene_time(b) for b in blocks]
    starts = [sum(durs[:i]) - i * XD for i in range(len(durs))]
    total = sum(durs) - XD * (len(blocks) - 1)
    sb_map = {sb["block_idx"]: sb for sb in story["blocks"]} \
        if story else {}
    seq = {"hook": 1, "insight": 2, "action": 3}
    seg_starts = {1: None, 2: None, 3: None}
    last_seg = 3
    for i, b in enumerate(blocks):
        source_idx = b.get("_source_idx", i)
        sb = sb_map.get(source_idx)
        if sb:
            beat_durs = beat_durations(scene_time(b), sb["beats"])
        else:
            beat_durs = [scene_time(b)]
        t = starts[i]
        for k, bd in enumerate(beat_durs):
            seg = _beat_segment(sb, k) if sb and k < len(sb["beats"]) \
                else None
            if seg in seq:
                last_seg = seq[seg]
            if seg_starts[last_seg] is None:
                seg_starts[last_seg] = t
            t += bd
    points = [seg_starts[1], seg_starts[2], seg_starts[3], total]
    # 空缺段用后一边界补齐，保证单调
    prev = 0.0
    for i in range(3):
        if points[i] is None or points[i] < prev:
            points[i] = prev
        prev = points[i]
    return points


CTA_CUES = ["咱们开始", "准备好了吗", "关注", "点赞", "收藏", "谢谢大家",
            "听完你就明白", "拆给你", "十几分钟"]
INSIGHT_CUES = ["摩根", "豪泽尔", "作者", "这本书", "《", "大师", "真相",
                "关系", "思维框架"]
HOOK_CUES = ["扎心", "焦虑", "空虚", "月底", "余额", "没钱", "负债",
             "欲望", "熬夜", "账单", "存款没多", "快乐没多", "翻倍"]


def _beat_segment(sb, k):
    """拍 segment：优先 LLM 标签，缺失时按旁白关键词 + 位置兜底。"""
    be = sb["beats"][k]
    seg = be.get("segment")
    if seg in ("hook", "insight", "action"):
        return seg
    sub_map = {s["id"]: s["text"] for s in sb.get("subtitles", [])}
    text = " ".join(sub_map[i] for i in be.get("sentence_ids", [])
                    if i in sub_map)
    if any(c in text for c in CTA_CUES):
        return "action"
    if any(c in text for c in INSIGHT_CUES):
        return "insight"
    if any(c in text for c in HOOK_CUES):
        return "hook"
    frac = k / max(1, len(sb["beats"]))
    if frac < 0.5:
        return "hook"
    if frac < 0.8:
        return "insight"
    return "action"


def transition_for(b, k):
    """按下一块类型选择 xfade 转场。"""
    btype = b["type"]
    if btype == "PHASE":
        return "zoomin"
    if btype == "QUOTE":
        return "circleopen"
    if btype == "TABLE":
        return "diagtr" if k % 2 == 0 else "diagtl"
    if btype == "STEPS":
        return "slideup"
    if btype == "CARD":
        return "smoothleft" if k % 2 == 0 else "smoothright"
    if btype == "TITLE":
        return "coverright"
    return "wipeup"


def finalize(blocks, out_name, seg_points=None):
    """xfade 视频转场 + acrossfade 音频 + 三段 BGM（Ducking/EQ）+ 全局响度。"""
    scenes = [PROJ("output", f"vs2_{i:02d}.mp4")
              for i in range(len(blocks))]
    durs = [scene_time(b) for b in blocks]
    n = len(scenes)
    if seg_points is None:
        t_total = sum(durs) - XD * (n - 1)
        seg_points = [0.0, t_total / 3, 2 * t_total / 3, t_total]
    music_paths = [find_music(i + 1) for i in range(3)]
    has_music = any(music_paths)
    cmd = ["ffmpeg", "-y"]
    for s in scenes:
        cmd += ["-i", s]
    seg_durs = [max(0.05, seg_points[i + 1] - seg_points[i])
                for i in range(3)]
    total = seg_points[3]
    if has_music:
        for i, mp in enumerate(music_paths):
            cmd += ["-stream_loop", "-1", "-t", f"{seg_durs[i]:.2f}",
                    "-i", mp]

    fc = []
    prev = "0:v"
    for k in range(n - 1):
        t = transition_for(blocks[k + 1], k)
        off = sum(durs[:k + 1]) - (k + 1) * XD
        out = f"vx{k}"
        fc.append(f"[{prev}][{k + 1}:v]xfade=transition={t}:"
                  f"duration={XD}:offset={off:.2f}[{out}]")
        prev = out
    fc.append(f"[{prev}]fade=t=out:st={sum(durs) - XD * (n - 1) - 0.5:.2f}"
              f":d=0.5[vf]")

    a_prev = "0:a"
    for k in range(n - 1):
        out = f"ax{k}"
        fc.append(f"[{a_prev}][{k + 1}:a]acrossfade=d={XD}[{out}]")
        a_prev = out
    if has_music:
        mi = n
        fc.append(f"[{a_prev}]volume=1.0[a0]")
        bgm_in = []
        for i in range(3):
            start_ms = int(seg_points[i] * 1000)
            fc.append(
                f"[{mi + i}:a]volume=0.16,"
                f"equalizer=f=1500:t=q:w=1.2:g=-2.5,"
                f"equalizer=f=2500:t=q:w=1.5:g=-2.5,"
                f"lowpass=f=8000,"
                f"afade=t=in:st=0:d=0.3,"
                f"afade=t=out:st={max(0.0, seg_durs[i] - 0.3):.2f}:d=0.3,"
                f"aformat=sample_rates=44100:channel_layouts=stereo,"
                f"adelay={start_ms}|{start_ms},"
                f"atrim=0:{total:.2f}[bgm{i}]")
            bgm_in.append(f"[bgm{i}]")
        fc.append("".join(bgm_in) +
                  f"amix=inputs=3:duration=longest:"
                  f"dropout_transition=0[bgm_mix]")
        fc.append(f"[bgm_mix][a0]sidechaincompress="
                  f"threshold=0.1:ratio=3:attack=60:release=800[bgm_duck]")
        fc.append(f"[a0][bgm_duck]amix=inputs=2:duration=first:"
                  f"dropout_transition=0,"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        fc.append(f"[{a_prev}]loudnorm=I=-14:TP=-1.5:LRA=11[a]")

    cmd += ["-filter_complex", ";".join(fc),
            "-map", "[vf]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-movflags", "+faststart",
            "-t", f"{total:.2f}",
            PROJ("output", out_name)]
    sh(*cmd)
    return PROJ("output", out_name)


def preview_frames(total, out_name):
    outdir = PROJ("output", "preview")
    os.makedirs(outdir, exist_ok=True)
    n = 10
    for k in range(n):
        t = total * (k + 0.5) / n
        sh("ffmpeg", "-y", "-ss", f"{t:.2f}",
           "-i", PROJ("output", out_name), "-frames:v", "1",
           "-vf", "scale=960:540", "-update", "1",
           os.path.join(outdir, f"{out_name[:-4]}_{k:02d}.jpg"))


def write_reports(blocks, total, out_name):
    rows = []
    for i, b in enumerate(blocks):
        rows.append({
            "序号": i + 1,
            "类型": b["type"],
            "标题": b["head"],
            "阶段": b["phase"] or "",
            "口播字数": len(b["voice"] or ""),
            "时长(秒)": round(scene_time(b), 2),
        })
    with open(PROJ("output", "storyboard_long.csv"), "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(PROJ("output", "long_summary.json"),
              "w", encoding="utf-8") as f:
        json.dump({"tts": "azure", "voice": azure_voice(),
                   "total_duration": round(total, 2),
                   "file": out_name, "blocks": rows},
                  f, ensure_ascii=False, indent=2)


def main():
    global NO_TTS, RUN_AZURE_VOICE
    ap = argparse.ArgumentParser(description="长视频 V5 渲染引擎")
    ap.add_argument("--project", default=None,
                    help="项目 id（默认取环境变量 PROJECT，缺省 001）")
    ap.add_argument("--pilot", action="store_true", help="只渲染前 5 个块")
    ap.add_argument("--frames", action="store_true",
                    help="快速抽帧：全块 2 秒无声片段各抽 3 帧，跳过 TTS 与合成")
    ap.add_argument("--blocks", default=None,
                    help="只渲染指定块（逗号分隔序号），如 0,1,2,3,4,7,8,9,12,13")
    ap.add_argument("--no-tts", action="store_true",
                    help="跳过配音合成：音轨静音，时长按字数估算")
    ap.add_argument("--workflow-run", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    if args.workflow_run:
        state_path = PROJ("workflow", "runs", args.workflow_run, "state.json")
        if not os.path.exists(state_path):
            raise FileNotFoundError(f"缺少 workflow run 快照：{state_path}")
        with open(state_path, encoding="utf-8") as handle:
            run_state = json.load(handle)
        if str(run_state.get("project_id")) != str(PJ.CURRENT_ID):
            raise RuntimeError("workflow run 与项目 id 不一致")
        speech = run_state.get("providers", {}).get("speech", {})
        if speech.get("name") != "azure" or not speech.get("voice"):
            raise RuntimeError("workflow run 的 speech 快照无效")
        RUN_AZURE_VOICE = speech["voice"]
    blocks = parse_script()
    for i, block in enumerate(blocks):
        block["_source_idx"] = i
    meta = book_meta(blocks)
    PJ.project_dir(title=meta[0], author=meta[2])
    story = load_storyboard()
    if args.blocks:
        kept = [int(x) for x in args.blocks.split(",") if x.strip()]
        blocks = [b for i, b in enumerate(blocks) if i in kept]
        if story:
            sb_map = {sb["block_idx"]: sb for sb in story["blocks"]}
            kept_sb = [sb_map[i] for i in kept if i in sb_map]
            story = {"blocks": kept_sb}
    if args.frames:
        render_frames_narrative(blocks, meta, story)
        print(f"FRAMES DONE 见 {PROJ('output', 'preview')}/m3n_*.jpg")
        return
    if args.pilot:
        blocks = blocks[:5]
    NO_TTS = args.no_tts
    if args.no_tts:
        for b in blocks:
            b["voice_dur"] = len(b["voice"] or "") / 4.0
    else:
        make_audio(blocks)
    total = len(blocks)
    for i, b in enumerate(blocks):
        render_scene_narrative(blocks, i, total, first=(i == 0),
                               last=(i == total - 1), meta=meta,
                               story=story)
    output_stem = f"long_{PJ.CURRENT_ID}"
    if args.blocks:
        out_name = output_stem + "_visual_sample.mp4"
    elif args.pilot:
        out_name = output_stem + "_pilot.mp4"
    else:
        out_name = output_stem + ".mp4"
    out = finalize(blocks, out_name,
                   compute_segments(blocks, story))
    dur = probe_dur(out)
    preview_frames(dur, out_name)
    write_reports(blocks, dur, out_name)
    print("DONE", out, "duration", round(dur, 2))


if __name__ == "__main__":
    main()
