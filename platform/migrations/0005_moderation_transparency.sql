-- Public moderation transparency (owner decision 2026-10-16).
-- Every hide/restore records the rule it cites (1-7, src/rules.ts; numbers are never reused or
-- renumbered), a short public note (<= 280 chars) and the moderator. The private `reason` stays staff-only.
-- The public record is the `content.hidden` / `content.restored` event: `actor_id` = moderator,
-- `data_json` = {"rule": n|null, "note": "..."|null}. Events written before this migration have neither.
ALTER TABLE moderation_actions ADD COLUMN rule INTEGER CHECK (rule IS NULL OR rule BETWEEN 1 AND 999);
ALTER TABLE moderation_actions ADD COLUMN public_note TEXT;

-- Hidden-post / hidden-comment pages look up the latest moderation event per object.
CREATE INDEX IF NOT EXISTS events_object ON events(object_type, object_number, seq);
