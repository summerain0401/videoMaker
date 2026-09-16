---
name: cover-design-lab
description: Explore and iteratively refine long-video cover designs before formal publishing. Use when the user wants to design, compare, critique, revise, or freeze a cover direction; do not use it to promote or finalize publishing assets.
---

# Cover Design Lab

Use Cover Lab as an exploratory workspace before the formal V4 cover workflow.
It may run for any number of rounds and may combine strengths from different
experiments. It must not create a publish ID, write to `publishing/`, select a
formal candidate, or promote/finalize an asset.

Version 1 supports `book_title_author_v2`. Keep `reference_006_v1` on its
existing formal path until a template-specific Cover Lab contract is added.

Read [references/design-package.md](references/design-package.md) before writing
or freezing a design package. Read
[references/ctr-design-guide.md](references/ctr-design-guide.md) when proposing
directions or reviewing experiments; it adapts `docs/youtube_cover_design.md`
to this repository rather than treating that source as a universal prompt.

## Start or resume a lab

1. Resolve the project and video run, then read the formal topic, brand palette,
   official scene references, character library, and the selected or intended
   cover-template definition. Do not silently choose a formal template.
2. Work only in
   `projects/{project}/experiments/cover_templates/{lab_id}/`. Use a stable,
   descriptive `lab_id`; resuming the same direction reuses it.
3. Inspect the existing `design.json`, feedback history, and experiment images
   before proposing the next round. Never discard prior feedback merely because
   a new image looks attractive.
4. Record the current working video title and explain how the cover hook adds a
   complementary question, consequence, or contradiction instead of repeating
   it. Mark this relationship provisional until the formal title is selected.

## Iterate by controlled decisions

- Separate the locked direction from execution variables. The locked direction
  is the concept, hook, visual metaphor, environment, optional character, and
  subtitle. Execution variables are only shot scale, composition, subject pose,
  and lighting.
- Early rounds may use three contrasting lenses—emotion, counter-intuitive
  conflict, and minimal symbolic curiosity—to discover a direction. They are
  exploration prompts, not a requirement that every topic use a face, split
  comparison, glowing prop, or exactly three candidates. Once the user favors
  one, preserve the accepted elements and change only the requested dimensions.
- Record every meaningful round in `feedback_history`: what the user liked,
  rejected, and what the next round must change. Translate vague feedback into
  observable design changes without inventing a new message or claim.
- Prefer inexpensive composition studies before polished generations. Compare
  candidates at full size and about 120 px thumbnail size; check focal hierarchy,
  title complementarity, duration-badge safety, text-safe area, emotional
  tension, topic traceability, and channel-style continuity.
- Do not treat the required final pair as two unrelated creative concepts. They
  must share one locked direction and differ only through controlled execution
  variables. Mixing A's composition with B's lighting is allowed when recorded.
- Generated experiment images remain experiments even if the user likes them.
  A formal cover must later be regenerated or imported through the publishing
  workflow and pass its normal image, composition, review, selection, and
  promotion gates.

## User gates

Show comparisons and continue iterating until the user explicitly says the
direction is approved or asks to freeze it. Satisfaction with one image is not
itself permission to freeze, import, select, promote, or finalize.

After explicit freeze approval:

1. Reduce the package to exactly the template's required candidate count,
   normally two controlled variants.
2. Ensure `design.json` validates as a draft and contains no provider, model,
   final prompt, negative prompt, publish ID, or formal asset path.
3. Run `cover-lab-freeze ... --confirm-freeze`. This creates an immutable
   `frozen_design.json`; never overwrite it. Further conceptual changes require
   a new lab ID.
4. In a V4 publish run, the user must still lock the same formal template. Then
   use `publish-cover-import-design --lab-id ...` and verify the imported plan.
   The formal workflow must not rewrite the frozen hook, metaphor, or concept.
5. After the user selects the formal publishing title, compare it with the
   frozen cover hook and run `publish-cover-title-check` with the user's explicit
   confirmation and a concrete explanation of their complementary suspense.
   Imported Cover Lab covers cannot be promoted while this hash-bound check is
   missing or stale.

Provider routing, native ImageGen signing, deterministic typography, visual
review, human selection, and promotion remain governed by
`video-maker-production` and the formal workflow.
