-- 012：滑翔机设计参数扩展（课程组需求）——机翼面积 / 整机质量 / 平尾偏角 / 垂尾偏角
-- 旧记录按默认值回填（默认值 = 既有行为，不影响历史结果解读）
ALTER TABLE glider_simulations ADD COLUMN wing_area REAL NOT NULL DEFAULT 17.5;
ALTER TABLE glider_simulations ADD COLUMN mass REAL NOT NULL DEFAULT 420;
ALTER TABLE glider_simulations ADD COLUMN elevator_deg REAL NOT NULL DEFAULT 0;
ALTER TABLE glider_simulations ADD COLUMN rudder_deg REAL NOT NULL DEFAULT 0;
