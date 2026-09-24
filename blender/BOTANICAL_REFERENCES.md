# 植物模型参考与制作说明

本次仅更新室内六盆植物与室外二十六丛灌木。参考图片用于观察形态，不下载或使用第三方摄影图片作为贴图；网格、叶脉纹理均由本项目 Blender 脚本生成。

- 鹤望兰 Strelitzia nicolai：参考 [Studioplant 叶片近照](https://www.studioplant.com/en/shop/strelitzia-nicolai-1728) 与 [feey 叶脉细节](https://www.feey-pflanzen.de/products/grosse-strelitzie)，提取大叶比例、中央叶脉、斜向侧脉、自然弯曲与边缘裂口。
- 黄杨 Buxus sempervirens：参考 [乌迪内大学 FLORA 叶片图片](https://mitel.dimi.uniud.it/flora/viewer/index.php?id=2530)，提取小椭圆叶、对生叶序与枝叶分层。模型是适合实时场景的形态近似，不是植物学标本复原。

## 模型结构

- 盆栽：有厚度的旋转体陶盆、卷边、盆内壁、凹入土面、颗粒、弯曲叶柄、生长中心卷叶、54 片曲面大叶及抬起的主叶脉。
- 灌木：从木质主干分出细枝，14,144 片小叶沿枝干成对分布，冠幅和色泽有所变化；不再用球体作为可见灌木外形。
- `vegetation.py` 负责生成；`refine_vegetation.py` 对现有源文件定点替换、核验其他对象、导出 GLB，并渲染两张近景。
- `vegetation-manifest.json` 保存生成统计。原始盆栽版模型保存在 `archive/hexu-library-before-botanical.blend`。

## 单独更新植物

```powershell
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/refine_vegetation.py
```

网页仍读取 `public/models/hexu-library.glb`。导出合并材质后约 12.53 MiB（13,133,420 字节）、70 个网格、328,642 个三角面；源场景中的每盆植物及每丛灌木保留单独命名的枝叶网格。架上 320 本书不由该文件导出，而由 `public/models/smart-book.glb` 在网页端实例化，因此这里的网格数与面数不含藏书。书架进深与图书摆放见 `SHELVING_REFERENCES.md`。
