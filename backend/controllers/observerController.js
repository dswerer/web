const service = require('../services/observerService');

function sendError(res, err) {
  if (err instanceof service.ObserverError) {
    return res.status(err.status).json({ error: err.message, code: err.code });
  }
  console.error('教师观察工作台错误:', err);
  return res.status(500).json({ error: '观察数据暂时不可用' });
}

exports.dashboard = (req, res) => {
  try { return res.json(service.dashboard(req.user)); } catch (err) { return sendError(res, err); }
};
exports.students = (req, res) => {
  try { return res.json(service.students(req.user, req.query)); } catch (err) { return sendError(res, err); }
};
exports.student = (req, res) => {
  try { return res.json(service.studentDetail(req.user, req.params.studentId)); } catch (err) { return sendError(res, err); }
};
