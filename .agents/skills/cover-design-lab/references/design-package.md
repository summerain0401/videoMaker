# Cover Lab design package

Write the mutable draft to
`projects/{project}/experiments/cover_templates/{lab_id}/design.json`.
Version 1 accepts only `book_title_author_v2`.

The exact top-level fields are:

```json
{
  "version": 1,
  "lab_id": "wealth_two_systems",
  "project_id": "001",
  "video_run_id": "run_video",
  "topic_sha256": "64 lowercase hex characters",
  "template_id": "book_title_author_v2",
  "status": "draft",
  "title_context": {
    "working_title": "the current provisional or selected video title",
    "relationship": "how title and cover hook create complementary suspense",
    "status": "provisional",
    "checked_at": null
  },
  "direction": {
    "concept": "one locked design direction",
    "hook": "4-16 Chinese characters",
    "hook_type": "pain_point",
    "subtitle": "0-14 characters or empty",
    "visual_metaphor": "one locked visual conflict",
    "environment": "one locked cinematic setting",
    "character_ids": [],
    "preserve": ["accepted observable element"],
    "avoid": ["rejected observable element"]
  },
  "variants": [
    {
      "id": "cover_a",
      "concept": "exactly direction.concept",
      "hook": "exactly direction.hook",
      "hook_type": "exactly direction.hook_type",
      "subtitle": "exactly direction.subtitle",
      "visual_metaphor": "exactly direction.visual_metaphor",
      "environment": "exactly direction.environment",
      "character_ids": [],
      "variant_controls": {
        "shot_scale": "medium close shot",
        "composition": "lower-center subject with diagonal causal path",
        "subject_pose": "reaching toward the escaping object",
        "lighting": "warm key light against cool environment"
      }
    }
  ],
  "feedback_history": [
    {
      "round": 1,
      "liked": ["clear focal subject"],
      "rejected": ["too many props"],
      "next_iteration": ["keep subject; reduce to one narrative object"]
    }
  ],
  "references": [
    {
      "id": "round_3_anchor",
      "path": "experiments/cover_templates/wealth_two_systems/round_3.png",
      "sha256": "64 lowercase hex characters",
      "purpose": "user-approved composition reference"
    }
  ],
  "frozen_at": null,
  "draft_sha256": null
}
```

`hook_type` is one of `pain_point`, `counter_intuitive`, or `warning`.
`title_context.status` is `provisional` or `confirmed`; a confirmed record must
contain `checked_at`. Formal publishing still performs a separate hash-bound
title check after the user selects the actual title.
`preserve`, `avoid`, and every feedback list must contain at least one concrete
string. `references` may be empty; referenced files must remain inside the
project and their hashes must match.

Exploratory drafts may contain any positive number of variants. Before freezing,
reduce them to the template's `candidate_count`. All frozen variants repeat the
locked direction exactly and must differ in `variant_controls`.

Do not manually set `status=frozen`, `frozen_at`, or `draft_sha256`; the freeze
command writes those values after validating the draft and explicit user gate.
