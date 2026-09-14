import json

sb = json.load(open('projects/013_影响力/input/candidates/run_20260913_074757/storyboard/storyboard.json'))

out = []
out.append('# 项目 013《影响力》统一语义分镜总览\n')
out.append('> **视频主题**：《越抢越亏？《影响力》揭秘社会认同与稀缺感如何瘫痪你的大脑，收割你的财富》  ')
out.append('> **核心角色**：周扬（年轻上班族 / `young_pro`）、西奥迪尼/导师（`author_morgan`）、焦虑大众（`stressed_worker` / `stressed_debtor`）  ')
out.append('> **规格总览**：共 33 块、57 拍，口播总字数 3966 字，100% 完整覆盖字幕。\n')

for b in sb['blocks']:
    btype = b['type']
    head = b.get('head', '')
    if btype == 'PHASE':
        out.append(f'\n---\n\n## {head}\n')
        continue
    if btype == 'END':
        out.append('\n---\n\n## 尾声 · END\n')
    elif btype == 'TITLE':
        out.append('\n## 开篇 · TITLE\n')
    else:
        out.append(f'\n### 块 {b["block_idx"]:02d} · {head}\n')

    if not b['beats']:
        continue

    for beat in b['beats']:
        bidx = beat['beat_idx']
        shot = beat['shot']
        vdesc = beat['visual_description']
        char = ', '.join(beat.get('character_ids') or ['无'])
        emotion = beat.get('emotion', '')
        sids = beat.get('sentence_ids', [])
        covered_text = ' '.join(b['subtitles'][sid]['text'] for sid in sids) if sids else '（片尾定格）'

        out.append(f'- **拍 {bidx}** `[{shot}]` `[角色: {char}]` `[情绪: {emotion}]`')
        out.append(f'  - **画面设定**：{vdesc}')
        out.append(f'  - **对应口播**：“{covered_text}”\n')

with open('/Users/spring/.gemini/antigravity/brain/b766aee5-6b44-410d-b4f4-93360c810918/storyboard_preview.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

print('Updated preview successfully')
