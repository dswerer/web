CREATE TABLE lesson_review_completions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  lesson_id INTEGER NOT NULL,
  completed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(student_id, lesson_id),
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
);

ALTER TABLE lesson_learning_reports ADD COLUMN score INTEGER CHECK(score BETWEEN 0 AND 100);

CREATE INDEX idx_lesson_review_completions_student
  ON lesson_review_completions(student_id, lesson_id);
