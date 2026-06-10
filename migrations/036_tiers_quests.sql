-- Move tier + quest definitions into DB (seeded defaults; editable without deploy)
CREATE TABLE IF NOT EXISTS tiers (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  min_rating INTEGER NOT NULL,
  color TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO tiers (key, name, min_rating, color, sort_order) VALUES
  ('bronze','Bronze',0,'#a1664b',1),
  ('silver','Silver',1000,'#8e9aa3',2),
  ('gold','Gold',1150,'#c8a233',3),
  ('platinum','Platinum',1300,'#3fa6a0',4),
  ('diamond','Diamond',1450,'#4f8cd6',5),
  ('master','Master',1600,'#9b5cd6',6),
  ('grandmaster','Grandmaster',1800,'#d65c5c',7);

CREATE TABLE IF NOT EXISTS quests (
  key TEXT PRIMARY KEY,
  scope TEXT NOT NULL,            -- daily | weekly
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  target INTEGER NOT NULL,
  reward_xp INTEGER NOT NULL,
  metric TEXT NOT NULL,          -- solved | high80 | categories
  is_active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO quests (key, scope, title, description, target, reward_xp, metric, is_active, sort_order) VALUES
  ('daily_solve','daily','Daily solve','Score a challenge today',1,50,'solved',1,1),
  ('daily_high','daily','Sharp shooter','Score 80+ on a challenge today',1,75,'high80',1,2),
  ('weekly_three','weekly','Consistent','Solve 3 challenges this week',3,150,'solved',1,3),
  ('weekly_categories','weekly','Explorer','Solve in 2 categories this week',2,150,'categories',1,4);
