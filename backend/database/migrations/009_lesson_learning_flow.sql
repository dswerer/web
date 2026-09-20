ALTER TABLE course_replays ADD COLUMN lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL;
ALTER TABLE resources ADD COLUMN lesson_id INTEGER REFERENCES lessons(id) ON DELETE SET NULL;
ALTER TABLE reflections ADD COLUMN report_id INTEGER REFERENCES lesson_learning_reports(id) ON DELETE SET NULL;

CREATE TABLE knowledge_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  content TEXT NOT NULL,
  key_points TEXT,
  common_mistakes TEXT,
  example_content TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_required INTEGER NOT NULL DEFAULT 1 CHECK(is_required IN (0,1)),
  estimated_minutes INTEGER,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
  created_by INTEGER NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE card_exercises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER NOT NULL,
  question_type TEXT NOT NULL CHECK(question_type IN ('single_choice','multiple_choice','true_false','fill_blank','short_answer')),
  prompt TEXT NOT NULL,
  options_json TEXT,
  answer_json TEXT NOT NULL,
  explanation TEXT,
  points INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_required INTEGER NOT NULL DEFAULT 1 CHECK(is_required IN (0,1)),
  max_attempts INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
);

CREATE TABLE card_exercise_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  exercise_id INTEGER NOT NULL,
  answer_json TEXT NOT NULL,
  is_correct INTEGER CHECK(is_correct IN (0,1)),
  score INTEGER NOT NULL DEFAULT 0,
  attempt_no INTEGER NOT NULL,
  submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (exercise_id) REFERENCES card_exercises(id) ON DELETE CASCADE
);

CREATE TABLE student_card_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  card_id INTEGER NOT NULL,
  viewed_at DATETIME,
  completed_at DATETIME,
  best_score INTEGER NOT NULL DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(student_id, card_id),
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
);

CREATE TABLE lesson_learning_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  lesson_id INTEGER NOT NULL,
  enrollment_id INTEGER,
  summary TEXT NOT NULL,
  key_points TEXT,
  application TEXT,
  difficulties TEXT,
  next_plan TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','submitted','approved','rejected')),
  parent_report_id INTEGER,
  version INTEGER NOT NULL DEFAULT 1,
  reviewer_id INTEGER,
  review_comment TEXT,
  submitted_at DATETIME,
  reviewed_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE,
  FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE SET NULL,
  FOREIGN KEY (parent_report_id) REFERENCES lesson_learning_reports(id) ON DELETE SET NULL,
  FOREIGN KEY (reviewer_id) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE(student_id, lesson_id, version)
);

-- 旧库中的回放和资源表字段可能少于当前 schema；迁移索引仅依赖本次新增列和主键。
CREATE INDEX idx_course_replays_lesson ON course_replays(lesson_id, id);
CREATE INDEX idx_resources_lesson ON resources(lesson_id, id);
CREATE INDEX idx_knowledge_cards_lesson ON knowledge_cards(lesson_id, status, sort_order, id);
CREATE INDEX idx_card_exercises_card ON card_exercises(card_id, sort_order, id);
CREATE INDEX idx_card_attempts_student_exercise ON card_exercise_attempts(student_id, exercise_id, attempt_no DESC);
CREATE INDEX idx_student_card_progress_student ON student_card_progress(student_id, card_id);
CREATE INDEX idx_learning_reports_student_lesson ON lesson_learning_reports(student_id, lesson_id, version DESC);
CREATE INDEX idx_learning_reports_review_queue ON lesson_learning_reports(status, submitted_at);
CREATE INDEX idx_reflections_report ON reflections(report_id);
