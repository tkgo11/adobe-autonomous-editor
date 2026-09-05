# Workflow Modules

This directory contains composable execution modules for the most common editing jobs. `SKILL.md` remains the autonomous entry point; it selects one primary workflow and zero or more overlays from this directory.

## Composition model

- Choose **one primary workflow** that best matches the dominant requested deliverable/editorial pattern.
- Add zero or more **supporting workflows** when another common pattern materially changes the edit (for example `short-form-vertical` + `talking-head`).
- Add **overlay workflows** for cross-cutting requirements such as captions/localization or multicam synchronization.
- If the brief clearly contains multiple deliverables, run one primary workflow per deliverable and share media analysis across them.
- Load only the modules needed for the current job. Do not inject every workflow into context.

## Primary workflows

| Module | Use when |
|---|---|
| `talking-head.md` | Single-speaker or presenter-led content, webcam/on-camera explanations, commentary |
| `short-form-vertical.md` | TikTok/Reels/Shorts-style vertical or square social edits |
| `youtube-longform.md` | Long-form YouTube/editorial videos with narrative structure, b-roll, chapters |
| `interview-podcast.md` | Interviews, podcasts, panel discussions, multi-speaker conversational edits |
| `tutorial-screencast.md` | Screen recordings, software tutorials, demos, educational walkthroughs |
| `event-highlight.md` | Weddings, travel, sports, events, highlight reels, cinematic montages |
| `commercial-product-ad.md` | Product promos, paid social ads, brand spots, direct-response commercials |
| `repurpose-master-to-social.md` | Turn a long master/interview/podcast into multiple short clips/variants |

## Overlay workflows

| Module | Use when |
|---|---|
| `captions-localization.md` | Burned-in captions, subtitle tracks, translation/localization, multiple language versions |
| `multicam-sync.md` | Multiple cameras and/or external audio require sync, angle switching, or multicam assembly |

## Required module contract

Every workflow module defines:

1. trigger conditions;
2. defaults that may be inferred without asking the user;
3. media-analysis priorities;
4. edit-plan rules;
5. Premiere execution rules;
6. After Effects escalation rules;
7. audio/color/graphics behavior;
8. verification and QC gates;
9. failure/fallback behavior;
10. deliverables and reusable artifacts.

See `workflow-contract.md` for the exact orchestration contract.
