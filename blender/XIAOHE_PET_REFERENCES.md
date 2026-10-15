# 小和 · 橙色像素宠物

## 形态参考

主参考为用户于 2026-10-15 提供的第二张截图，保存在 [原始参考](references/xiaohe-pet-reference.png)。它是 63 × 53 px 的小图，主体橙色为 `#D87656`。辅助观察了 [Anthropic Claude Code 仓库中的 Clawd 截图讨论](https://github.com/anthropics/claude-code/issues/13755)，只观察轮廓，没有下载外部贴图或第三方模型。本项目的角色名仍为“小和”，模型与动画代码由本项目自行生成。

原先的小和是 Three.js 的着色器光球，不在图书馆 `.blend` 中。改前实际渲染见 [前台光球](xiaohe-before-desk.png)，改后 Blender 实际渲染见 [四分之三视角](xiaohe-pet-three-quarter.png) 与 [正面](xiaohe-pet-front.png)。

## 几何与比例

按参考图中橙色像素逐行量取：全宽 43 px、总高 29 px；身体 29 × 21 px；左右手臂各 7 × 7 px；四条腿高 8 px，宽分别为 3、4、4、4 px；眼睛为两个 5 × 4 px 的黑色块。单像素对应 `0.78 / 43` 米，因此全宽 0.78 m、高约 0.526 m、厚 0.26 m。

保留方块轮廓，只做 0.7–4 mm 的单段倒角，使用哑光陶土橙材质和黑色方眼，没有添加嘴、触角或多余装饰。GLB 共 9 个网格、16 个节点、396 个三角面，36,072 字节，无纹理与外部依赖。独立文件 `xiaohe-pet.blend` 包含可编辑身体、眼睛、手臂与腿，以及摄影棚灯光与相机；仅角色节点导出到网页。

## 动画接口

`src/scene/companion.js` 加载 `public/models/xiaohe-pet.glb`，提供导航锚点 `root`、`update()` 和只读状态。手臂节点 `PetArmLeft/Right`、四条腿 `PetLeg1..4` 可单独旋转；`PetEyeLeft/Right` 支持眨眼。待机轻微悬浮、呼吸和眨眼；唤醒时抬手、放大和橙色底部波纹；导航及归还时摆腿。角色朝向随相机调整，保证从前台与书架看过去都能看到眼睛。

原有前台位置 `[0, 1.2, 5]`、导航路径、书籍坐标、唤醒词、多轮语音和对话气泡契约均保留。`libraryDebug` 的旧 `orb` 字段继续表示导航锚点，新增 `companion` 描述实际宠物，避免现有测试与诊断入口失效。

## 重建与不变量

先复制项目到临时目录，在副本中执行：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_xiaohe_pet.py
```

`xiaohe_pet.py` 是确定性的几何生成模块；`build_xiaohe_pet.py` 只重建独立角色，并用 SHA-256 快照断言图书馆 `.blend`、环境 GLB、两块书本 GLB 和唯一馆藏清单没有变化。脚本验证网格数、包围盒、面数，再导出 GLB、渲染两张视图并保存可编辑 `.blend`。首次已在 `.cache/pet-model-work/` 副本中执行，查看实际渲染和清单后才复制新产物到仓库。

若该角色文件已经存在，后续改动仍须在副本中构建、对比后再替换，不能直接覆盖成品。`tools/package-local.mjs` 会携带并检查角色 GLB；不需要重建书架或馆藏坐标。

网页实际模型加载后的 [前台待机](xiaohe-after-desk.png) 与 [唤醒抬手](xiaohe-awake-desk.png) 也已取证；独立浏览器检查确认仅唤醒不移动导航锚点，眨眼缩放与腿部行进动画实际变化。
