# AGENTS.md

本仓库的工作约定见 [DEVELOPMENT.md](./DEVELOPMENT.md)，动手前先读它。以下是要点，完整说明以该文档为准。

## 每次改动后自动提交并推送

完成一个「改动」后直接提交并推送，**不需要额外征求确认**。一个「改动」= 一件完成且已验证的逻辑变更，不是每次保存文件。

1. 先验证：跑 `npm test`；涉及界面、场景或交互的改动，另外在浏览器里回归完整链路（加载场景 → 找书 → 翻开封面 → 查看芯片 → 放回书架 → 回到待命）。
2. 提交：Conventional Commits 前缀（`feat` / `fix` / `docs` / `refactor` / `chore` / `test`）+ 中文描述，写清**为什么**改。一次提交只做一件事。提交信息用 `git commit -F -` 配合 heredoc 传入。
3. 推送：`git push origin master`。

## 硬性约束

- **凭据绝不写入任何文件。** 令牌只在环境变量 `GITEE_ACCESS_TOKEN` 中（仅调用 Gitee REST API 时需要）；推送用 SSH 密钥 `~/.ssh/id_ed25519`，无需令牌。不要把令牌、私钥或任何凭据字面量写进源码、文档、示例、测试或提交信息。
- **命令行不要传中文。** Git Bash 会把 argv 里的 UTF-8 中文转成 GBK 字节，导致服务端收到 `U+FFFD` 乱码。需要传非 ASCII 内容时改用文件传参。
- **不要提交** `node_modules/`、`blender/__pycache__/`、`blender/*.blend1`、`.mimosa/`。`archive/` 下的 `.blend` 是有意保留的版本备份，应当提交。
- **不要直接覆盖仓库内的模型成品。** 改动 Blender 脚本后，先把项目复制到临时目录跑重建，与现有产物对比确认无误。
- **改动馆藏坐标后**，重跑 `node tools/prepare-smart-books.mjs` 并重建模型，保持三份清单副本一致。
