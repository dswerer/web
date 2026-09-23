#version 330

// line.vert —— 航迹线 / 地面网格线的顶点着色器
//
// 顶点属性：in_position（世界系坐标，m）
// uniform ：u_mvp（= u_proj * u_view * u_model，线几何直接传世界系顶点，模型矩阵为单位阵）

in vec3 in_position;

uniform mat4 u_mvp;

void main() {
    gl_Position = u_mvp * vec4(in_position, 1.0);
}