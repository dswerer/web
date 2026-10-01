-- 013：滑翔机轨迹数据表（每帧位置/姿态的持久化，最小向量接口 ftrc 格式）
-- 模拟只产出数据（flight_trace.bin）→ 后端入库 → 接口读库 → 独立渲染程序生成视频。
CREATE TABLE IF NOT EXISTS glider_trajectories (
  simulation_id INTEGER PRIMARY KEY,
  format TEXT NOT NULL DEFAULT 'ftrc-f32/1',
  frame_count INTEGER NOT NULL,
  state_dim INTEGER NOT NULL,
  frames BLOB NOT NULL,   -- flight_trace.bin 原始字节（20B 头 + float32 帧矩阵），zlib 压缩
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (simulation_id) REFERENCES glider_simulations(id) ON DELETE CASCADE
);
