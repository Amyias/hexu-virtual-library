# AGENTS.md

本仓库的工作约定见 [DEVELOPMENT.md](./DEVELOPMENT.md)，动手前先读它。以下是要点，完整说明以该文档为准。

## 每次改动后自动提交并推送

完成一个「改动」后直接提交并推送，**不需要额外征求确认**。一个「改动」= 一件完成且已验证的逻辑变更，不是每次保存文件。

1. 先验证：跑 `npm test`；涉及界面、场景或交互的改动，另外在浏览器里回归完整链路（加载场景 → 找书 → 翻开封面 → 查看芯片 → 放回书架 → 回到待命）。
2. 提交：Conventional Commits 前缀（`feat` / `fix` / `docs` / `refactor` / `chore` / `test`）+ 中文描述，写清**为什么**改。一次提交只做一件事。提交信息用 `git commit -F -` 配合 heredoc 传入。
3. 推送：`git push github master`。GitHub 仓库 `Amyias/hexu-virtual-library` 是唯一的权威仓库（本机远端名 `github`；从 GitHub 新克隆的副本里它叫 `origin`）。Gitee 不再推送。

## 自动提交推送的边界

用户已授权完成改动后自动提交并推送，无需逐次确认。该授权**仅限**：

- 只推 GitHub 仓库 `Amyias/hexu-virtual-library` 的 `master`，不新增远端、不改远端地址；
- 不执行 force push，不改写已推送的历史；
- 提交内容不得包含任何凭据值或私钥内容。

越出以上范围的对外操作——新建或删除仓库、修改仓库设置、推送其它远端、把仓库转为公开——**先征得用户确认**。

## 发行版附件规则

- 源码提交和 GitHub Release 是两件事：`git push` 不会上传 `dist/` 的发行附件，发版必须另行运行 `tools/release.mjs`。
- 每个新发行版必须同时包含 `hexu-library-<版本>-program.zip` 与 `sense-voice-<版本>.zip`，即使模型内容没有变化。旧版本里的模型包不能代替当前版本附件。
- 新版本先创建草稿，两个附件校验完整后才公开发布；上传失败保留草稿待补传，不把缺附件的版本作为完成品发布。
- `--no-model` 仅用于当前发行版已有完整、带 SHA-256 的模型附件时更新程序包；缺模型必须失败，不得报告发布成功。
- 补传模型使用 `node tools/release.mjs --assets-only --model-only`，保留已发布程序包与标签，不为补附件改版本号。
- 完成后通过 GitHub API 验证两个附件均为 `uploaded`、大小大于零并有 SHA-256；本次上传的附件大小和摘要必须与本地 ZIP 完全一致。模型 ZIP 还须通过 CRC 检查并包含非空 ONNX 与词表。
- `dist/`、`.cache/` 与模型 ZIP 继续不进入 `master` 历史；模型包发布到 GitHub Release。更新已有发行版附件是已授权的发布维护范围，不包含删除整个发行版或改写标签。

## 凭据（硬性约束，无例外）

凭据的位置与配置方式见 [DEVELOPMENT.md](./DEVELOPMENT.md) 的「凭据」一节，需要时再去读。

- **绝不读取、打印、回显、记录或上传凭据值。** 不要把凭据变量展开到命令输出、日志、临时文件、提交信息或任何对外请求里。凭据只在该工具真正需要它的那一次调用中从环境变量读取，不复制、不缓存、不写入磁盘。
- **绝不把凭据字面量写入任何文件**——源码、文档、示例、测试、提交信息都不行。文件中只允许出现变量名与路径。
- 若某次输出可能包含凭据值，先遮蔽再输出。
- 不需要凭据的任务（例如日常提交推送走 SSH），不要去读取凭据。
## 其它硬性约束

- **命令行不要传中文。** Git Bash 会把 argv 里的 UTF-8 中文转成 GBK 字节，导致服务端收到 `U+FFFD` 乱码。需要传非 ASCII 内容时改用文件传参。
- **不要提交** `node_modules/`、`blender/__pycache__/`、`blender/*.blend1`、`.mimosa/`。`archive/` 下的 `.blend` 是有意保留的版本备份，应当提交。
- **不要直接覆盖仓库内的模型成品。** 改动 Blender 脚本后，先把项目复制到临时目录跑重建，与现有产物对比确认无误。
- **Blender 在 `D:\Blender Foundation\Blender 5.2\blender.exe`。** 做模型精细化时按 [DEVELOPMENT.md](./DEVELOPMENT.md) 的「模型精细化的做法」执行：先渲染取证 → 网上找形态参考（只用来看，不下载贴图）→ 写生成模块 → 写带不变量断言的定点替换脚本 → 写 `blender/<部件>_REFERENCES.md` → 验证 → 同步 README。
- **改动馆藏坐标后**，重跑 `node tools/prepare-smart-books.mjs` 并重建模型。清单只有 `public/models/book-inventory.json` 一份，示例书的内容与位置写在 `blender/demo-shelf-map.json`。
