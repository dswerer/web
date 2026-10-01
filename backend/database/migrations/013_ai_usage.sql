-- 仅记录运行元数据，不保存提问、课程资料、回答或密钥。
CREATE TABLE IF NOT EXISTS ai_usage (
  id TEXT PRIMARY KEY,
  user_id INTEGER,
  course_id INTEGER,
  request_day TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','succeeded','failed')),
  error_code TEXT,
  provider_request_id TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  total_tokens INTEGER,
  duration_ms INTEGER,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
  FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_day_user ON ai_usage(request_day, user_id);
