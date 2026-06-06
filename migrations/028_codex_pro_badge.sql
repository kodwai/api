-- Codex Pro badge (parity with Claude Master / Cursor Pro)
INSERT OR IGNORE INTO badges (id, name, slug, description, icon, category, criteria) VALUES
('badge_codex_pro', 'Codex Pro', 'codex-pro', 'Score 80+ on 5 challenges using Codex', 'terminal', 'special', '{"type":"agent_score","agent":"codex","min_score":80,"min_count":5}');
