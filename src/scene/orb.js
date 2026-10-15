import * as THREE from "three";
export function createOrb(scene, home) {
  // Procedural Siri-like flowing energy orb: shader, glow sprites, animated rings.
  const orb = new THREE.Group();
  orb.position.copy(home);
  scene.add(orb);
  const coreMaterial = new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, boost: { value: 0 } },
    vertexShader:
      "varying vec3 vNormal; varying vec3 vPos; uniform float time; void main(){vNormal=normal;vPos=position;float d=1.0+0.045*sin(position.y*10.0+time*2.0)*cos(position.x*9.0-time);gl_Position=projectionMatrix*modelViewMatrix*vec4(position*d,1.0);}",
    fragmentShader:
      "varying vec3 vNormal;varying vec3 vPos;uniform float time;uniform float boost;void main(){float f=sin(vPos.x*10.0+time*1.7+sin(vPos.y*9.0-time*2.0)*2.0)*0.5+0.5;vec3 c=mix(vec3(0.12,0.85,0.72),vec3(0.38,0.32,0.95),f);c=mix(c,vec3(0.95,0.57,0.86),pow(max(0.0,sin(vPos.y*13.0+time)),3.0)*0.7);float edge=pow(1.0-abs(vNormal.z),2.0);gl_FragColor=vec4(c+edge*0.4+boost*0.24,1.0);}",
  });
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.27, 48, 48), coreMaterial);
  orb.add(core);
  const glowCanvas = document.createElement("canvas");
  glowCanvas.width = glowCanvas.height = 128;
  const gc = glowCanvas.getContext("2d");
  const gradient = gc.createRadialGradient(64, 64, 4, 64, 64, 64);
  gradient.addColorStop(0, "rgba(159,246,224,.7)");
  gradient.addColorStop(0.35, "rgba(122,219,207,.25)");
  gradient.addColorStop(1, "rgba(120,190,180,0)");
  gc.fillStyle = gradient;
  gc.fillRect(0, 0, 128, 128);
  const glow = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(glowCanvas),
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  glow.scale.set(1.3, 1.3, 1);
  orb.add(glow);
  const rings = [];
  for (let i = 0; i < 3; i++) {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.31, 0.008, 8, 80),
      new THREE.MeshBasicMaterial({
        color: ["#91e9d6", "#b9a5f0", "#a6d7de"][i],
        transparent: true,
        opacity: 0.7,
        depthWrite: false,
      }),
    );
    ring.rotation.set(i * 0.9, 0.6 + i * 0.6, 0.3);
    orb.add(ring);
    rings.push(ring);
  }

  return { orb, coreMaterial, core, glow, rings };
}
