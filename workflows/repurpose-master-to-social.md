# Workflow: Repurpose Long Master into Social Clips

## Trigger

Use when the source is a long interview, podcast, webinar, lecture, livestream, or finished master and the requested result is multiple short social clips.

## Default assumptions

- reuse shared transcript/semantic analysis once;
- each output must make sense without requiring the viewer to watch the master;
- avoid generating many near-duplicate clips merely to satisfy quantity;
- prefer quality/diversity of hooks and topics.

## Analysis priorities

Score candidate ranges for:

- standalone completeness;
- strong first sentence/hook;
- emotional or informational payoff;
- quotability;
- controversy/surprise only when genuinely present, not manufactured;
- duration suitability;
- visual crop quality;
- overlap with already selected clips.

## Edit plan

1. Build a candidate segment pool with semantic labels and scores.
2. Deduplicate overlapping ideas.
3. Select a diverse set of strongest segments.
4. For each clip, load `short-form-vertical.md` when vertical delivery is requested or inferred.
5. Add concise context only if necessary for standalone comprehension.
6. Create independent titles/captions/CTAs when requested.
7. Batch-render variants while retaining a shared source sequence/reference.

## Premiere rules

- maintain one source/master reference sequence plus one versioned sequence per clip;
- avoid destructive edits to the source master;
- use programmatic sequence duplication and naming;
- batch export with deterministic file naming.

## QC gates

Reject and repair if:

- two deliverables are substantially redundant;
- a clip begins mid-thought without enough context;
- the hook misrepresents the later statement;
- captions/titles use context from a different clip;
- batch exports have wrong aspect ratio or duration.
