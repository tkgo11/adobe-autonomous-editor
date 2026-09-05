# Overlay: Multicam / External Audio Synchronization

## Trigger

Load when two or more cameras and/or separately recorded audio cover the same event or conversation.

## Analysis priorities

- camera/audio clock metadata;
- waveform correlation;
- clap/slate/transient events;
- timecode compatibility;
- drift over long takes;
- dropped/paused recordings;
- per-angle quality and coverage gaps.

## Sync strategy

Use the strongest available method in this order:

1. matching embedded timecode;
2. reliable jam-synced metadata;
3. waveform/audio correlation;
4. visual slate/clap/transient alignment;
5. agent-driven vision-assisted UI alignment as the last resort; never delegate alignment to the user.

Never assume one offset is sufficient for a long take if devices can drift.

## Execution rules

- create synchronized source groups/multicam sequences non-destructively;
- keep high-quality external audio as the preferred program source when appropriate;
- preserve scratch camera audio for sync/recovery;
- detect and compensate for gradual drift when measurable;
- split/re-sync around camera stops or discontinuities;
- label angles consistently.

## Angle selection policy

Angle changes should depend on:

- active speaker/action;
- framing quality;
- reaction value;
- continuity;
- avoidance of camera bumps/focus failures;
- user style requirements.

Do not switch angles on a fixed interval merely to create motion.

## QC gates

Reject and repair if:

- lip sync or impact sync is visibly wrong;
- sync drifts later in a take;
- a camera discontinuity causes a timeline jump;
- wrong/scratch audio is accidentally used in the final mix;
- angle labels map to the wrong source.
