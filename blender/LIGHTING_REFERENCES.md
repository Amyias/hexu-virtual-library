# 日光、吊灯与地面接触阴影

网页光源与 Blender 对照渲染共用 `public/models/lighting-rig.json`。日光来自后侧拱窗，八个暖色吊灯位于真实灯具的下方，两盏阅读灯补充桌面照明。灯罩原有发光材质增强，但金属灯壳保持不透明；低视角能看见发光扩散板，高视角不会把整个灯壳变成发光条。

参考与实现依据：

- [Three.js 灯光与阴影](https://threejs.org/manual/en/shadows.html)：阴影相机、投射者和接收者必须同时配置；多光源阴影增加绘制成本。
- [LightShadow](https://archive.threejs.org/docs/api/en/lights/shadows/LightShadow.html)：PCF 的 radius 决定滤波范围，bias 与 normalBias 必须按场景米制尺度调整。当前使用 PCFShadowMap，日光 4096（窄屏 2048），吊灯 512，减少原先 35 mm 法线偏移造成的接触脱离。
- [Blender Ambient Occlusion 节点](https://docs.blender.org/manual/en/latest/render/shader_nodes/input/ao.html)：使用真实几何的环境遮蔽烘焙地面接触，而不是手画椭圆阴影。范围 0.72 m，2048×2048，无外部贴图下载。

`blender/bake_lighting.py` **只读副本，不保存或改写源 .blend，也不重新导出 GLB**。先以 `HEXU_LIGHTING_MODE=before` 渲染原场景，再以 `bake` 生成 AO 及新灯光参考。源模型全部网格的名称、变换、顶点数和面数在烘焙前后必须一致。接收平面在地板顶面 7.5 mm 之上，位于 12 mm；平均亮度断言拒绝埋入地板导致的全黑烘焙。

流程（PowerShell，在仓库根目录；先复制 .blend 与贴图到工作目录）：

```powershell
$env:HEXU_LIGHTING_WORK = (Resolve-Path .cache/lighting-work).Path
$env:HEXU_LIGHTING_MODE = 'bake'
& 'D:/Blender Foundation/Blender 5.2/blender.exe' --background --factory-startup --python-exit-code 1 --python blender/bake_lighting.py
```

确认 `lighting-bake.json` 中 `geometry_unchanged` 为 true，检查 AO、对照渲染和浏览器画面后，才将工作目录中的 `public/textures/library-contact-ao.png` 复制入库。已有扫描贴图和 GLB 几何保持原样。网页仅将石基层藏在木板下面的顶面设为暗色衬底，窗台和外露基座不变，以消除板缝露出的白色基层。

实时渲染采用方向光／聚光灯阴影与烘焙 AO 的组合，并非实时路径追踪：天空与间接反弹光是近似补光；静态 AO 只记录固定环境，活动书本使用实时阴影。吊灯在待命和固定阅读特写时缓存阴影，在取书／归还动画期间实时更新，切换状态时刷新一次；日光阴影持续更新。`tests/fixtures/lighting.html` 提供无界面遮挡的真实模型检查，`tests/lighting.test.mjs` 校验 AO 内容与灯具位置。

预留书本实例保留原编号、矩阵和槽位容量，但绘制数量只延伸到最后一本可见书。空书库绘制零本，避免一万多个零缩放空槽位仍执行多光源顶点着色器；取书和归还后重算绘制范围，不改变真实馆藏位置。
