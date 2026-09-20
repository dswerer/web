const express = require('express');
const controller = require('../controllers/observerController');
const { requireAuth, requirePasswordChanged, requireRole } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);
router.use(requirePasswordChanged);
router.use(requireRole('teacher', 'admin'));

router.get('/', controller.dashboard);
router.get('/students', controller.students);
router.get('/students/:studentId', controller.student);

module.exports = router;
