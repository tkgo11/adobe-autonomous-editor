# Overlay: Captions / Subtitles / Localization

## Trigger

Load when the user requests captions, subtitles, burned-in text, SRT/VTT, translated versions, or multiple language deliverables.

## Analysis priorities

- final edited dialogue timing;
- speaker changes;
- proper nouns/brand terms;
- punctuation and sentence boundaries;
- reading speed;
- on-screen collision regions;
- source-language ambiguity.

## Execution rules

1. Transcribe from source or final dialogue with word-level timing.
2. Reconcile transcript against the **final edited sequence**.
3. Correct obvious ASR mistakes using audio/context and supplied names.
4. Segment into readable phrase units.
5. Apply speaker labels only when useful/required.
6. For localization, translate meaning rather than preserving source word order mechanically.
7. Preserve product names, legal wording, measurements, and proper nouns appropriately.
8. Generate requested subtitle files and/or burned-in captions.
9. Reflow translated captions independently because text expansion differs by language.

## Premiere / AE routing

- Use Premiere caption tracks when they satisfy styling/delivery needs.
- Use graphics templates or AE only when advanced caption animation is required.
- Keep an editable subtitle source file even when captions are burned into video.

## QC gates

Reject and repair if:

- caption timing is based on removed source speech;
- text meaning disagrees with audible speech;
- reading speed is unreasonable;
- text overlaps faces, UI, legal text, or platform exclusion zones;
- translation omits or invents material information;
- exported subtitle file contains invalid or overlapping timing unless intentional.
