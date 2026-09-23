#version 330

// aircraft.frag —— 飞机模型的片段着色器
//
// 本着色器实际使用：u_light_dir / u_light_color / u_ambient / u_base_color /
//                   u_highlight / u_cam_eye（边缘补光）/ u_alt（高空大气透视）
// 其余契约内的 uniform（见 aircraft.vert 顶部注释）由渲染器逐帧上传，
// 想用哪个直接在此声明即可，无需改动 Python。
//
// 单位约定：u_alt 为米，u_highlight 为 0/1。

in vec3 v_normal_world;
in vec3 v_color;
in vec3 v_world_pos;
in vec3 v_local_pos;

uniform vec3 u_light_dir;
uniform vec3 u_light_color;
uniform vec3 u_ambient;
uniform vec4 u_base_color;
uniform float u_highlight;
uniform vec3 u_cam_eye;
uniform float u_alt;

out vec4 fragColor;

const vec3 SKY = vec3(0.53, 0.72, 0.94);

void main() {
    // 双面光照：OBJ 模型绕向不定、盒体部件很薄，法线一律朝向观察者
    vec3 N = normalize(v_normal_world);
    vec3 Vv = normalize(u_cam_eye - v_world_pos);
    if (dot(N, Vv) < 0.0) {
        N = -N;
    }
    vec3 L = normalize(u_light_dir);

    float ndl = max(dot(N, L), 0.0);
    vec3 base = v_color * u_base_color.rgb;
    vec3 lit = base * (u_ambient + u_light_color * ndl);

    // 边缘补光（fresnel）：让白色机身在天空底色下仍有立体轮廓
    float fres = pow(1.0 - clamp(dot(N, Vv), 0.0, 1.0), 3.0);
    lit += u_light_color * fres * 0.22;

    // 高空大气透视：高度越高，机身越被天空色"洗淡"
    float haze = clamp(u_alt / 4000.0, 0.0, 0.6);
    lit = mix(lit, SKY, haze);

    // 高亮（失控/失速等异常状态）
    lit = mix(lit, vec3(0.95, 0.15, 0.15), u_highlight * 0.55);

    fragColor = vec4(clamp(lit, 0.0, 1.0), u_base_color.a);
}