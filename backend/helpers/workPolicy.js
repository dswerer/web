// 作品权限策略（决策 D-1/D-2/D-6）。
// work 行需携带：student_id / student_teacher_id / student_school_id / review_status / enrollment_id / course_id / has_newer_version。
const { courseBelongsToMentor } = require('./courseScope');

function belongsToTeacher(user, work) {
  if (user.role !== 'teacher') return false;
  if (work.student_teacher_id) return work.student_teacher_id === user.id;
  // 历史学生尚未分配负责教师时，兼容其本校教师；显式分配后只认负责教师。
  return !!user.school_id && work.student_school_id === user.school_id;
}

// 评审：admin 全部；导师仅自己课程（含授课归属）；教师仅负责学生的关联报名作品
function canReviewWork(user, work) {
  if (user.role === 'admin') return true;
  // 遗留无报名关联的作品（enrollment_id/course_id 缺失）按决策 D-2：仅管理员可见
  if (!work.enrollment_id || !work.course_id) return false;
  if (user.role === 'teacher') return belongsToTeacher(user, work);
  if (user.role !== 'academic_mentor') return false;
  return courseBelongsToMentor(user.id, work.course_id);
}

// 查看：admin 全部；导师=可评审范围；学生=本人；教师=负责学生的全部已关联报名作品
function canViewWork(user, work) {
  if (user.role === 'admin') return true;
  if (user.role === 'academic_mentor') return canReviewWork(user, work);
  if (user.role === 'student') return work.student_id === user.id;
  return belongsToTeacher(user, work)
    && !!work.enrollment_id
    && !!work.course_id;
}

// 删除（决策 D-6）：学生可删 pending 或被打回的最新版本；
// 导师/教师/media 禁止；admin 仅限异常处理（已通过/有后续版本同样禁止）
function canDeleteWork(user, work) {
  if (user.role === 'admin') {
    return work.review_status !== 'approved' && !work.has_newer_version;
  }
  if (user.role === 'student' && work.student_id === user.id) {
    if (work.review_status === 'approved') return false;
    if (work.has_newer_version) return false;
    return work.review_status === 'pending' || work.review_status === 'rejected';
  }
  return false;
}

module.exports = { canViewWork, canReviewWork, canDeleteWork };
