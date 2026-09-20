// 设计令牌：颜色与间距统一入口，新页面优先从本文件取值，
// 逐步替代各页面散落的 inline style 常量。
export const colors = {
  primary: '#1a73e8',
  primarySoft: '#eaf2ff',
  surface: '#ffffff',
  border: '#e5eaf0',
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
  textSecondary: '#5f6368',
  pageBg: '#f5f7fa',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
};

export const radius = 8;
export const shadows = { card: '0 8px 24px rgba(31, 45, 61, 0.06)' };
