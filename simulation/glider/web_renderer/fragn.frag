precision highp float;
in vec2 vUv;

uniform sampler2D u_g_position;
uniform sampler2D u_g_normal;
uniform sampler2D u_g_albedo;
uniform mat4 u_inv_view_proj;
uniform vec3 u_cam_eye;
uniform vec3 u_light_dir;
uniform vec3 u_light_color;
uniform vec3 u_ambient_up;
uniform vec3 u_ambient_down;
uniform vec3 u_fog_color;
uniform vec3 u_ground_albedo;
uniform float u_fog_density;
uniform float u_grid_spacing;
uniform float u_grid_fade_dist;

out vec4 fragColor;


// 回放时间 (s)：驱动 sky_color 中采样起点 from 的平移（暂停即静止）
uniform float u_time;

#define iterations 20
#define formuparam 0.7

#define volsteps 20
#define stepsize 0.1

#define zoom   0.800
#define tile   0.850
#define speed  0.010 

#define brightness 0.0015
#define darkmatter 0.300
#define distfading 0.730
#define saturation 0.850


vec3 sky_color(vec3 dir)
{
  float time=u_time*0.0005;
	vec3 from=vec3(1.,.5,0.5)+vec3(time*2.,time,-2.);
	
	//volumetric rendering
	float s=0.1,fade=1.;
	vec3 v=vec3(0.);
	for (int r=0; r<volsteps; r++) {
		vec3 p=from+s*dir*.5;
		p = abs(vec3(tile)-mod(p,vec3(tile*2.))); // tiling fold
		float pa,a=pa=0.;
		for (int i=0; i<iterations; i++) { 
			p=abs(p)/dot(p,p)-formuparam; // the magic formula
			a+=abs(length(p)-pa); // absolute sum of average change
			pa=length(p);
		}
		float dm=max(0.,darkmatter-a*a*.001); //dark matter
		a*=a*a; // add contrast
		if (r>6) fade*=1.-dm; // dark matter, don't render near
		//v+=vec3(dm,dm*.5,0.);
		v+=fade;
		v+=vec3(s,s*s,s*s*s*s)*a*brightness*fade; // coloring based on distance
		fade*=distfading; // distance fading
		s+=stepsize;
	}
	v=mix(vec3(length(v)),v,saturation); //color adjust
    v=tanh(v*.01);
	return v;
	
}

void main() {
    vec4 pos_f = texture(u_g_position, vUv);
    vec4 nrm_f = texture(u_g_normal, vUv);
    vec4 alb = texture(u_g_albedo, vUv);
    // vec3 L = normalize(u_light_dir);
    vec3 L = vec3(0.,-1.,0.);

    if (pos_f.w < 0.5) {//背景部分
        vec4 far = u_inv_view_proj * vec4(vUv * 2.0 - 1.0, 1.0, 1.0);
        vec3 ray = normalize(far.xyz / far.w - u_cam_eye);

        if (ray.y < -1e-4) {
            float t = -u_cam_eye.y / ray.y;
            vec3 wp = u_cam_eye + ray * t;
            float dist = t;
            float ndl = max(L.y, 0.0);
            // vec3 lit = u_ground_albedo * (u_ambient_up + u_light_color * ndl);
            vec3 lit=vec3(0.);

            vec2 coord = wp.xz / u_grid_spacing/2.;
            vec2 grid = abs(fract(coord - 0.5) - 0.5) / fwidth(coord);
            float line = 1.0 - min(min(grid.x, grid.y), 1.0);
            float fade = 1.0 - smoothstep(u_grid_fade_dist * 0.1, u_grid_fade_dist, dist);
            lit = mix(lit, lit * 1.6 + vec3(0.90,0.70,0.10), line * fade);

            vec3 sky = sky_color(ray * vec3(1.0, 1.0, 1.0));
            sky = mix(sky, u_fog_color, smoothstep(0.02, -0.08, -ray.y));
            float fade2 = 1.0 - smoothstep(0.0, u_grid_fade_dist * 7.0, dist);
            fragColor = vec4((lit + sky * (1.0 - fade2 * 0.2)) / 2.0, 1.0);
        } else {
            vec3 sky = sky_color(ray);
            sky = mix(sky, u_fog_color, smoothstep(0.02, -0.08, ray.y));
            fragColor = vec4(sky, 1.0);
        }
        return;
    }

    float dist = length(u_cam_eye - pos_f.xyz);
    vec3 N = normalize(nrm_f.xyz);
    vec3 V = normalize(u_cam_eye - pos_f.xyz);
    float ndl = max(dot(N, L), 0.0);
    vec3 H = normalize(L + V);
    float spec = pow(max(dot(N, H), 0.0), 40.0) * 0.25;
    vec3 ambient = mix(u_ambient_down, u_ambient_up, 0.5 * N.y + 0.5);
    vec3 s_col=vec3(0.90,0.90,0.30);
    vec3 lit = alb.rgb * (ambient + s_col * ndl) + s_col * spec;
    float fog = 1.0 - exp(-u_fog_density * dist);
    lit = mix(lit, u_fog_color, fog);//模型部分
    fragColor = vec4(lit, 1.0);
}