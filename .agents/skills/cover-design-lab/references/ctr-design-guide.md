# Adapted YouTube cover design guide

Use this guide for Cover Lab ideation and review. It adapts
`docs/youtube_cover_design.md` to the repository's provider, style, and formal
publishing boundaries.

## Hard constraints

- Keep indispensable information outside the lower-right duration-badge area
  defined by the selected template. Keep critical content within the template's
  outer safe margins.
- Limit the immediate hierarchy to the emotional subject or gesture, one core
  conflict object, and locally composed short copy. Reduce competing background
  detail through depth, contrast, and lighting; do not add an empty panel or
  break the continuous full-frame scene.
- Image generation produces a clean base without readable text, typography,
  logos, timestamps, or watermarks. Deterministic local composition adds the
  book title, hook, and subtitle.
- The cover hook must not mechanically repeat the working or selected video
  title. Record how the pair forms a question/answer, cause/consequence, or
  expectation/contradiction relationship.
- Preserve the official video style and supplied references. Never force
  photorealism, anime, 3D rendering, or another fashionable style when it
  conflicts with the project.

## Exploration lenses

Use these as contrasting hypotheses in an early round when helpful:

- Emotion: a legible expression or gesture directs attention to the conflict.
- Counter-intuitive conflict: one surprising object relationship contradicts
  the expected outcome without using a cluttered split comparison.
- Minimal symbolic curiosity: one enlarged metaphorical object and strong
  negative space create curiosity without decorative glow or generic spectacle.

Do not force all three, promise CTR, or preserve these labels in the frozen
package. After the user selects a direction, converge to one locked concept and
two controlled execution variants.

## Heuristics, not universal rules

- Prefer a 4–8 Chinese-character hook. Use 9–12 only when meaning would be lost;
  13–16 requires a successful thumbnail legibility check.
- Separate subject and background with value, warm/cool contrast, depth, or
  natural rim light. Avoid artificial edge glow, fixed light rings, and heavy
  vignette unless the chosen project style genuinely calls for them.
- Keep the typography region calm and low-detail while allowing natural scenery
  and texture to continue through it. Do not create a blank caption band.

## Review at each meaningful round

- At roughly 120 px, is the subject-object conflict still understandable?
- Does the eye move from subject or gesture to the core object and then copy?
- Is the lower-right badge area free of critical faces, hands, and objects?
- Does the hook add suspense instead of restating the video title?
- Is the subject separated without breaking official video style?
- Are there no more than three immediate focal elements?

Store the user's likes, rejections, and next-round constraints in
`feedback_history`. Do not store a provider-specific final prompt in the design
package; the formal workflow compiles sealed image tasks later.
