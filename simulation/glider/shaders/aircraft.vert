#version 330

// aircraft.vert —— 飞机模型的顶点着色器
//
// 顶点属性
//   in_position : 机体系局部坐标 (m)
//   in_normal   : 机体系法线
//   in_color    : 顶点色（程序化网格 = 部件颜色；OBJ 网格 = 统一色）
//
// 本着色器实际使用：u_model / u_view / u_proj / u_normal_mat
// 其余由渲染器逐帧上传、可在此直接声明使用的 uniform（完整契约见 render_gl.UNIFORM_CONTRACT）：
//   变换  : u_mvp
//   姿态  : u_pos u_quat u_euler u_vel u_omega u_scale
//   状态  : u_alt u_V u_alpha u_beta u_CL u_CD u_sink
//            u_bank u_pitch u_heading u_elevator u_aileron u_rudder u_time u_frame
//   相机  : u_cam_eye u_cam_target u_cam_up u_fovy u_near u_far u_resolution
//   光照  : u_light_dir u_light_color u_ambient u_base_color u_highlight

in vec3 in_position;
in vec3 in_normal;
in vec3 in_color;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_normal_mat;

out vec3 v_normal_world;
out vec3 v_color;
out vec3 v_world_pos;
out vec3 v_local_pos;

void main() {
    vec4 world = u_model * vec4(in_position, 1.0);
    v_world_pos = world.xyz;
    v_local_pos = in_position;
    v_normal_world = normalize((u_normal_mat * vec4(in_normal, 0.0)).xyz);
    v_color = in_color;
    gl_Position = u_proj * u_view * world;   // 等价于 u_mvp * vec4(in_position, 1.0)
}