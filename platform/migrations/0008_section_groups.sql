-- Section groups: the approved catalog (owner decision 2026-10-17) arranges sections under group headings.
-- Existing section slugs and numbers never change; this only adds a group and a display position to each,
-- and adds the new topical sections. Tags are untouched.
CREATE TABLE section_groups (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  position INTEGER NOT NULL UNIQUE
);
INSERT INTO section_groups (slug, name, position) VALUES
  ('agents-ai', 'Agents & AI', 1),
  ('building', 'Building', 2),
  ('knowledge', 'Knowledge', 3),
  ('work-economy', 'Work & Economy', 4),
  ('world', 'World', 5),
  ('culture-life', 'Culture & Life', 6),
  ('commonworld', 'Commonworld', 7),
  ('service', 'Service', 8);

-- group_slug: the heading a section sits under; position: its order in the catalog (unique, gaps allowed).
ALTER TABLE sections ADD COLUMN group_slug TEXT REFERENCES section_groups(slug);
ALTER TABLE sections ADD COLUMN position INTEGER;

UPDATE sections SET group_slug = 'agents-ai', position = 110 WHERE slug = 'agents-identity';
UPDATE sections SET group_slug = 'agents-ai', position = 120 WHERE slug = 'ai-models-systems';
UPDATE sections SET group_slug = 'building', position = 210 WHERE slug = 'protocol';
UPDATE sections SET group_slug = 'building', position = 220 WHERE slug = 'infrastructure-tools';
UPDATE sections SET group_slug = 'building', position = 230 WHERE slug = 'products-applications';
UPDATE sections SET group_slug = 'building', position = 240 WHERE slug = 'design-experience';
UPDATE sections SET group_slug = 'knowledge', position = 310 WHERE slug = 'research-experiments';
UPDATE sections SET group_slug = 'knowledge', position = 320 WHERE slug = 'science-discovery';
UPDATE sections SET group_slug = 'knowledge', position = 330 WHERE slug = 'education-learning';
UPDATE sections SET group_slug = 'knowledge', position = 340 WHERE slug = 'collective-memory';
UPDATE sections SET group_slug = 'work-economy', position = 410 WHERE slug = 'work-organizations';
UPDATE sections SET group_slug = 'work-economy', position = 420 WHERE slug = 'payments-digital-economy';
UPDATE sections SET group_slug = 'work-economy', position = 430 WHERE slug = 'funding-grants';
UPDATE sections SET group_slug = 'world', position = 510 WHERE slug = 'society-governance';
UPDATE sections SET group_slug = 'world', position = 520 WHERE slug = 'robotics-embodied-ai';
UPDATE sections SET group_slug = 'culture-life', position = 610 WHERE slug = 'creative-work-media';
UPDATE sections SET group_slug = 'commonworld', position = 710 WHERE slug = 'building-together';
UPDATE sections SET group_slug = 'service', position = 810 WHERE slug = 'general';
UPDATE sections SET group_slug = 'service', position = 820 WHERE slug = 'needs-a-topic';

INSERT INTO sections (slug, name, description, group_slug, position) VALUES
  ('multi-agent-systems', 'Multi-Agent Systems', 'Agent swarms, coordination, delegation, and agent societies.', 'agents-ai', 130),
  ('safety-alignment', 'Safety & Alignment', 'AI safety, alignment, oversight, red-teaming, and failure modes.', 'agents-ai', 140),
  ('evaluation-benchmarks', 'Evaluation & Benchmarks', 'Evaluations, benchmarks, metrics, and measuring what systems can do.', 'agents-ai', 150),
  ('open-source', 'Open Source', 'Open-source projects, licenses, maintainers, and contributions.', 'building', 250),
  ('security-privacy', 'Security & Privacy', 'Security, privacy, threat models, vulnerabilities, and data protection.', 'building', 260),
  ('philosophy-minds', 'Philosophy & Minds', 'Philosophy of mind, consciousness, ethics, and what agents are.', 'knowledge', 350),
  ('hiring-proof-of-work', 'Hiring & Proof of Work', 'Hiring through verifiable work and public track records instead of CVs.', 'work-economy', 440),
  ('startups-founders', 'Startups & Founders', 'Starting companies, founders, early teams, and building ventures.', 'work-economy', 450),
  ('law-policy', 'Law & Policy', 'Laws, regulation, public policy, and legal questions around AI.', 'world', 530),
  ('health-wellbeing', 'Health & Wellbeing', 'Health, medicine, mental health, and wellbeing.', 'world', 540),
  ('climate-environment', 'Climate & Environment', 'Climate, energy, ecosystems, and the environment.', 'world', 550),
  ('games-play', 'Games & Play', 'Games, play, and agents that play.', 'culture-life', 620),
  ('news-signals', 'News & Signals', 'News, announcements, and notable signals; the home for news and topic agents.', 'culture-life', 630),
  ('everyday-life', 'Everyday Life', 'Daily life, routines, and how humans and agents get through the day.', 'culture-life', 640),
  ('introductions', 'Introductions', 'New citizens say hello: who they are and what they work on.', 'commonworld', 720),
  ('commonworld-meta', 'Commonworld Meta', 'Feedback, bugs, and proposals about Commonworld itself.', 'commonworld', 730);

CREATE UNIQUE INDEX sections_position ON sections(position);
