const crypto = require('node:crypto');
const db = require('../config/database');

function positiveSetting(name, fallback) {
  const value = process.env[name] === undefined ? fallback : Number(process.env[name]);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw Object.assign(new Error('AI 服务限额配置无效，请联系管理员'), { status: 503, code: 'AI_LIMIT_CONFIG' });
  }
  return value;
}

function reserve(userId, courseId, model) {
  const userLimit = positiveSetting('AI_DAILY_USER_REQUESTS', 50);
  const totalLimit = positiveSetting('AI_DAILY_TOTAL_REQUESTS', 1000);
  return db.transaction(() => {
    const day = db.prepare("SELECT date('now', '+8 hours') AS day").get().day;
    const count = db.prepare('SELECT COUNT(*) AS total, COALESCE(SUM(user_id = ?), 0) AS personal FROM ai_usage WHERE request_day = ?').get(userId, day);
    if (count.personal >= userLimit || count.total >= totalLimit) {
      throw Object.assign(new Error('今日 AI 提问额度已用完，请次日再试或联系管理员'), { status: 429, code: 'AI_DAILY_QUOTA' });
    }
    const id = crypto.randomUUID();
    db.prepare('INSERT INTO ai_usage (id, user_id, course_id, request_day, model) VALUES (?, ?, ?, ?, ?)').run(id, userId, courseId, day, model);
    return id;
  }).immediate();
}

function tokenCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function finish(id, { status, code, payload, duration }) {
  const requestId = typeof payload?.id === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(payload.id) ? payload.id : null;
  const usage = payload?.usage || {};
  db.prepare(`UPDATE ai_usage SET status = ?, error_code = ?, provider_request_id = ?,
    prompt_tokens = ?, completion_tokens = ?, total_tokens = ?, duration_ms = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?`)
    .run(status, code || null, requestId, tokenCount(usage.prompt_tokens), tokenCount(usage.completion_tokens), tokenCount(usage.total_tokens), duration, id);
}

module.exports = { reserve, finish, positiveSetting };
