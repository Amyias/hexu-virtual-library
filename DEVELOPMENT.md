# 开发与提交约定

本文件记录本项目的工作流约定、远端仓库信息与凭据位置。动手改代码前请先读完。

## 每次改动后：验证 → 提交 → 推送

一个「改动」指**一件完成且已验证的逻辑变更**，不是每次保存文件。流程固定三步，不需要额外确认。

### 1. 验证

- 任何改动都先跑 `npm test`。当前 6 项：馆藏几何与书架结构、`hexu-library.glb` 合并契约、`smart-book.glb` 部件命名、三份馆藏清单副本一致性、ASR 生命周期。
- 涉及界面、场景、动画或交互的改动，另外在浏览器里回归一遍完整链路：加载场景 → 找书 → 翻开封面 → 查看芯片 → 放回书架 → 回到待命。
- 改动 Blender 脚本后，**先把项目复制到临时目录跑重建**，与现有产物对比，不要直接覆盖仓库里的成品模型。

### 2. 提交

使用 Conventional Commits 前缀 + 中文描述：

| 前缀 | 用途 |
| --- | --- |
| `feat` | 新增能力 |
| `fix` | 修复缺陷 |
| `docs` | 文档 |
| `refactor` | 重构（行为不变） |
| `chore` | 构建、依赖、杂务 |
| `test` | 测试 |

提交信息要写清**为什么**改，而不只是改了什么。一次提交只做一件事，不要把无关改动混在一起。

提交信息用 heredoc 传入，避免经过命令行参数（原因见下文「编码陷阱」）：

```bash
git commit -F - <<'MSG'
fix: 一句话说明修了什么

需要记下的背景与取舍。
MSG
```

### 3. 推送

```bash
git push origin master
```

## 远端仓库

| 项 | 值 |
| --- | --- |
| 平台 | Gitee |
| 仓库 | `li-tao-yi/hexu-virtual-library` |
| 地址 | https://gitee.com/li-tao-yi/hexu-virtual-library |
| 可见性 | 私有 |
| 默认分支 | `master` |
| 远端 | `git@gitee.com:li-tao-yi/hexu-virtual-library.git` |

远端使用 SSH，因此**推送不需要任何令牌**。

## 凭据

**凭据值不写入任何文件。** 本仓库的源码、文档、示例与测试中只出现变量名与路径，绝不含明文令牌或私钥。

处理凭据时不可例外地遵守：

- 绝不读取、打印、回显、记录或上传凭据值；不要把它展开到命令输出、日志、临时文件、提交信息或任何对外请求里。
- 凭据只在该工具真正需要它的那一次调用中从环境变量读取，不复制、不缓存、不写入磁盘。
- 若某次输出可能包含凭据值，先遮蔽再输出。
- 不需要凭据的任务（例如日常提交推送走 SSH），不要去读取凭据。

### 推送认证：SSH 密钥

| 项 | 位置 |
| --- | --- |
| 私钥 | `~/.ssh/id_ed25519`（即 `C:\Users\<用户名>\.ssh\id_ed25519`） |
| 公钥 | `~/.ssh/id_ed25519.pub`，已登记到 Gitee 账号 |
| 验证 | `ssh -T git@gitee.com`，成功时返回 `Hi 李焘屹(@li-tao-yi)!` |

密钥位于用户目录，不在仓库内，也不会被提交。

### API 认证：Gitee 个人访问令牌

仅调用 Gitee REST API（新建仓库、修改仓库描述等）时需要；日常提交推送用不到。

| 项 | 位置 |
| --- | --- |
| 变量名 | `GITEE_ACCESS_TOKEN` |
| 存放 | Windows 环境变量，明文 `REG_SZ` |
| 用户级 | `HKCU\Environment` |
| 系统级 | `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment` |
| 所需权限 | 至少 `user_info`（读账号）与 `projects`（建仓库） |

检查是否已配置（不会打印令牌内容）：

```bash
test -n "$GITEE_ACCESS_TOKEN" && echo "已配置" || echo "未配置"
```

读取与持久化设置：

```powershell
# 查看。会显示明文值，注意不要把输出粘贴进任何文件或对话
reg query "HKCU\Environment" /v GITEE_ACCESS_TOKEN

# 持久化设置，新开终端后生效
setx GITEE_ACCESS_TOKEN "<你的令牌>"
```

> 当前令牌在用户级与系统级各有一份，系统级那份本机所有用户与进程都能读到。若只想给当前用户使用，可删除系统级那份，只保留用户级。

## 编码陷阱：命令行不要传中文

Git Bash 会把命令行参数里的 UTF-8 中文转成 GBK 字节再交给程序。**建库时仓库描述就是这样损坏的**——服务端收到 64 个 `U+FFFD` 替换字符。

传给外部程序非 ASCII 内容时，一律改为文件传参：

```bash
# 错误：中文经 argv 传递会被破坏
curl -X PATCH "$API" -d "description=中文描述"

# 正确：内容先写入 UTF-8 文件，由程序读取
curl -X PATCH "$API" --data-urlencode "description@/path/to/desc.txt"
```

`git commit -F -` 配合 heredoc 是安全的（heredoc 不经过 argv），提交信息不会损坏。

## 不应提交的内容

`.gitignore` 已排除：

| 路径 | 原因 |
| --- | --- |
| `node_modules/` | 项目无 npm 依赖，仅工具缓存 |
| `blender/__pycache__/`、`*.pyc` | Python 字节码 |
| `blender/*.blend1` | Blender 保存时自动生成的上一版备份 |
| `.mimosa/` | 本机安全扫描插件的钩子状态，与项目无关 |

`archive/` 下的 `.blend` 是**有意保留**的版本备份（植物精细化前、芯片体系前），应当提交。

`public/models/*.glb`、`blender/*.blend`、贴图与渲染图都在仓库内，这是项目的设计意图：模型与渲染依赖随项目分发，不依赖外部 CDN。

## 常用命令

```powershell
npm start                      # 本地服务，http://localhost:8080
npm test                       # 回归测试

# 全量重建模型：覆盖 .blend / .glb / 贴图 / 预览
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python-exit-code 1 --python blender/build_library.py

# 在 Blender 手动编辑并保存后，只重新导出与渲染，不重建
& 'D:\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup blender/hexu-library.blend --python-exit-code 1 --python blender/export_saved.py

# 重新生成馆藏清单（一次写入三份副本，必须保持一致）
node tools/prepare-smart-books.mjs
```

改动馆藏坐标后，应重跑 `prepare-smart-books.mjs` 并重建模型，避免书籍与预留槽位不一致。

## 已知的脚本间隐式耦合

`export_saved.py` 通过 `exec` 复用 `build_library.py` 中「`# Merge by collection`」之后的合并段，`refine_books.py` 与 `refine_vegetation.py` 又 `exec` 了 `export_saved.py`。三者共享同一个全局命名空间，`static_books` 等变量正是靠这个机制在脚本间传递。

改动这段管线时注意：**在 `build_library.py` 里把这类变量写成字面量，会切断 `export_saved.py` 的赋值通路**。

安全扫描工具会把这几处 `exec` 报为「代码注入」。经核查不构成注入漏洞——没有任何不可信输入进入 `exec`，被执行的本来就是仓库内自行维护的文件。但这是真实的**可维护性缺陷**，重构时应改为显式函数调用。目前保持原样，以免影响已验证的导出结果。
