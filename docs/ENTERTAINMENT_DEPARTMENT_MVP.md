# Entertainment Department MVP

The Entertainment Department converts **already-sanitized** AI Cockpit events into an internal editorial queue.

## Pipeline

`sanitized Cockpit events -> story scoring -> MANGA / X / YOUTUBE draft queue -> Owner review`

The first implementation deliberately creates structured outlines, not autonomous public posts. A qualifying story becomes three channel-specific draft records:
- MANGA: 4-beat comic outline
- X: 3-beat post outline
- YOUTUBE: 5-beat video outline

The existing story score remains the common prioritization signal so editorial selection is deterministic and auditable.

## Safety boundary

Unsanitized events are rejected by the existing public-event sanitizer. Every output is `DRAFT_INTERNAL`, requires Owner approval, and has `external_publish_allowed=false`. The module contains no social-media API, credential, broker, order, Scheduled Task, or real-submit path.

## Next layer

Future adapters may turn these records into character dialogue, panels, thumbnails, scripts, and bilingual copy. Publication remains a separate explicit approval action.
