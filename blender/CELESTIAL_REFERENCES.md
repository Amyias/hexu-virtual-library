# 像素太阳与月亮

## 形态参考

只观察公开的像素画教程，提取比例与配色规律，没有下载任何贴图或第三方模型：

- [Pixnote：像素太阳 16×16 画法](https://pixnote.net/en/learn/draw-sun/)——圆盘 + 短而粗、贴近本体的四向光芒；2–3 个黄到橙的色阶，光源在左上，右下压一圈偏橙的暗色，不用黑色描边。
- [Mega Voxels：How to Make a Pixel Art Sun](https://www.megavoxels.com/learn/how-to-make-a-pixel-art-sun/)——底部一圈暗黄勾边增加体积感，顶部一侧用浅色高光。
- [CSS Pixel Art Weather & Sky](https://abduarrahman.com/blog/css-pixel-art-weather-sky-10-effects/)——月牙用三个暖白色阶；太阳光芒做轻微呼吸动画。
- 月牙取“两圆相减”的通用画法：大圆减去向一侧偏移的小圆。

渲染见 [太阳](celestial-sun.png) 与 [月亮](celestial-moon.png)。

## 生成参数

`celestial.py` 在 22 × 22 的像素网格上生成两块体素，单像素 0.08 m、厚一格 0.08 m；只输出与空格相邻的面，保持方块轮廓且面数很少。

| 天体 | 构成 | 色值 |
| --- | --- | --- |
| 太阳 `PixelSun` | 半径 6.3 格圆盘（`PixelSunDisc`）；四向 3 格光芒与四个 2×2 斜向光芒，均与圆盘隔一格（`PixelSunRays`）；全宽 1.76 m | 主体 `#F7C53B`、右下暗部 `#E9962F`、左上高光 `#FFE89A`、光芒 `#F2AE36` |
| 月亮 `PixelMoon` | 半径 7 格圆减去向右上偏移 (4, 2.5) 的半径 6 格圆；内缘一格暗部、四个陨石坑（`PixelMoonFace`）；月牙开口处一个十字星与两颗单像素星（`PixelMoonStars`） | 月面 `#F1E8C6`、内缘 `#D4C597`、陨石坑 `#C2B286`、星 `#FFF4CF` |

太阳 168 个像素、928 个三角面；月亮与星 88 个像素、508 个三角面；GLB 共 4 个网格、约 52 KiB，没有纹理。材质带同色自发光，网页加载后改为不受灯光、雾与色调映射影响的纯色材质，保持像素颜色准确，也不投射阴影。

## 摆放位置

窗侧日光在 `lighting-rig.json` 中从 `[-8, 12, -19]` 照向 `[0, 0, -2]`，即左后方窗外，所以地上的影子朝右前方。天体放在 `rig.sky.position = [-4.94, 2.4, -12.5]`：

- **方位与日光一致**：水平面上与光线方向共线（`tests/sky.test.mjs` 断言叉积为零且在光源同侧），影子正好背离太阳。
- **高度为可见性压低**：日光真实仰角约 32°，沿光线放置会落到所有总览画面之外。改为放在第二扇拱窗（x = −5）外、花园矮墙之后，从默认、正面、拉远与左侧视角都能透过同一扇窗看到，并被窗框真实遮挡。
- 天体只绕竖直轴转向相机，像素面始终朝向读者且不倾斜。

## 日月切换

右下角的「☾ / ☀」按钮在两种天空之间切换，选择保存在浏览器本地（`hexu-sky`）。月亮占用太阳的同一位置，`lighting.setNight()` 只改变颜色与强度，不移动光源，所以切换前后阴影方向不变：

- 日光变为冷色月光（3.1 → 1.2），半球光与补光减弱，背景与雾变为夜蓝 `#232B3E`，环境反射减到 35%；
- 吊灯 12 → 70、灯罩自发光 3 → 8、阅读灯 0.65 → 1.6，夜里八盏吊灯成为主要光源，光圈落到走道地面与书架正面；
- 太阳下沉缩小后月亮升起，过渡 1.4 秒按真实时间推进，不受帧率影响；页面文字同步改为浅色。

## 重建与不变量

先在临时目录构建、检查渲染与清单，再把产物复制回仓库：

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_celestial.py -- --out <临时目录>
```

不带 `--out` 时直接写入仓库。脚本用 SHA-256 快照断言图书馆 `.blend`、环境与书本 GLB、小和 GLB、馆藏清单和灯光配置都没有变化；验证网格数、尺寸与面数后导出 `public/models/celestial.glb`，渲染两张预览，保存可编辑的 `celestial.blend` 与 `celestial-manifest.json`。两次构建的 GLB 字节完全一致。`tools/package-local.mjs` 已携带并检查该 GLB，旧桌面程序需要重新打包才会显示。
