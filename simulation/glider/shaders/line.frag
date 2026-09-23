#version 330

// line.frag —— 航迹线 / 地面网格线的片段着色器（纯色，不做光照）

uniform vec4 u_color;

out vec4 fragColor;

void main() {
    fragColor = u_color;
}