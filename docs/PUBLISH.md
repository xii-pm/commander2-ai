# 发布到 GitHub：完整操作指南

本目录已经是一个**可直接推送的 git 仓库内容**：源码、`README.md`、`LICENSE`（MIT）、
`.gitignore`、CI、测试、文档都齐了，只差最后三步——装 Git、建远程仓库、推送。

> 仓库名建议：`commander2-ai`（GitHub 仓库名只能用 ASCII 字母/数字/`-`/`_`/`.`，
> **不支持中文**；中文队名放在 README 标题和仓库 Description 里）。
> 本仓库的 Badge 与远程地址按 `xii-pm/commander2-ai` 写好，如果用户名不同，
> 全局替换这两处即可（见第 6 节）。

## 五分钟版

```powershell
# 1) 安装 Git（Windows）
winget install --id Git.Git -e --source winget
#    或从 https://git-scm.com/download/win 下载安装包，一路默认

# 2) 配置身份（只需一次）
git config --global user.name  "伍家齐"
git config --global user.email "你的邮箱@example.com"

# 3) 在仓库目录初始化并提交
cd "D:\竞赛（已完结）\您说的队-github"
git init -b main
git add .
git commit -m "feat: Commander-II AI agent, 2026 ISCIIA First Prize"

# 4) 去 GitHub 网页新建一个空仓库（Public，不要勾 README/.gitignore/License），
#    然后把远程地址接上并推送
git remote add origin https://github.com/xii-pm/commander2-ai.git
git push -u origin main
```

第 4 步执行 `git push` 时会弹出登录窗口（Git Credential Manager）或用 Token 认证，
见第 3 节。推送成功后打开 `https://github.com/xii-pm/commander2-ai` 即可看到仓库。

---

## 1. 先确认本地环境

```powershell
git --version          # 需要 2.30+；没有就装
git config --global user.name
git config --global user.email
```

当前这台机器**还没有安装 Git**，`github.com` 也**直连不通**（需要代理或镜像，见第 4 节），
所以下面每一步都给出"没网怎么办"的替代方案。如果你在别的机器上操作，跳过对应小节即可。

## 2. 安装 Git

三种方式，任选：

| 方式 | 命令/地址 | 说明 |
| --- | --- | --- |
| winget | `winget install --id Git.Git -e --source winget` | 最省事，自动进 PATH |
| 官方安装包 | https://git-scm.com/download/win | 一路默认即可 |
| GitHub Desktop | https://desktop.github.com/ | 图形界面，自带 Git；适合不想敲命令 |

装完**重开一个终端**再执行 `git --version` 验证。GitHub Desktop 用户可以直接用它的
"Add local repository → 选择本目录"，然后在界面里 Publish repository，等价于第 3、5 步。

## 3. 建立 GitHub 远程仓库并认证

### 3.1 网页建空仓库

1. 打开 https://github.com/new
2. **Repository name** 填 `commander2-ai`
3. **Description** 填：`您说的队 · Commander-II AI 智能体（2026 ISCIIA 一等奖）`
4. 选 **Public**（开源）或 **Private**（先私有，检查完再公开）
5. **不要**勾选 "Add a README file"、`.gitignore`、`license`——本地都已经有了，
   勾了会产生一次无关的合并
6. Create repository，复制页面上给出的 HTTPS 地址

### 3.2 认证方式（二选一）

**A. Token（推荐，跨平台稳定）**

1. GitHub → Settings → Developer settings → Personal access tokens →
   **Fine-grained tokens**（或 Tokens classic）→ Generate new token
2. 权限只需 `Contents: Read and write`（classic 勾 `repo`）
3. 复制 token（只显示一次）
4. 首次 `git push` 时用户名填 GitHub 用户名，**密码处粘贴 token**

> 不要让 token 出现在任何文件、命令历史或 remote URL 里。要缓存可以用
> `git config --global credential.helper manager`，让系统凭据管理器保存。

**B. SSH 密钥**

```powershell
ssh-keygen -t ed25519 -C "你的邮箱"
# 一路回车（可设密码）
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"   # 复制这一行
```

粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key，然后把远程地址改成
`git@github.com:xii-pm/commander2-ai.git`。

## 4. 网络：国内直连 GitHub 失败的常见解法

当前机器 `https://github.com` 直连超时。按顺序尝试：

**4.1 走代理（最常用）**

```powershell
# 假设本地代理端口 7890（Clash/V2Ray 等），换成你自己的
git config --global http.proxy  http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890

# 取消
git config --global --unset http.proxy
git config --global --unset https.proxy
```

**4.2 SSH 走 443 端口**（22 端口被墙时很有效）

`%USERPROFILE%\.ssh\config` 写入：

```
Host github.com
    HostName ssh.github.com
    Port 443
    User git
```

**4.3 用 GitHub Desktop 推送**（它有自己的网络处理，通常比命令行更容易连通）

**4.4 完全没网时的兜底：网页上传**

1. 在 GitHub 新建仓库后点 "uploading an existing file"
2. 用 Chrome/Edge 把整个文件夹**拖进**页面（支持拖目录）
3. 提交信息填 `feat: initial release`

限制：单次拖拽文件数有上限（约 100 个）、单文件 <25 MB、**没有提交历史**。
本仓库约 110 个文件（95 个 `.py` + 文档），需要分两批拖，或者只拖源码+README，
文档部分用网页 "Add file → Create new file" 补。**不推荐**，但网络实在不通时可用。

## 5. 首次提交与推送

```powershell
cd "D:\竞赛（已完结）\您说的队-github"

git init -b main
git add .
git status                 # 确认没有 __pycache__、没有大压缩包
git commit -m "feat: Commander-II AI agent, 2026 ISCIIA First Prize"

git remote add origin https://github.com/xii-pm/commander2-ai.git
git branch -M main
git push -u origin main
```

`git status` 那一步很关键：确认**只有源码、文档、配置、ci**，没有 `__pycache__/`、
没有 18 GB 的赛事压缩包、没有答辩 PPT（`.gitignore` 已经排除这些，但最好亲眼确认一次）。

提交信息建议再补一行正文：

```
feat: Commander-II AI agent, 2026 ISCIIA First Prize

- 95 modules, 15.4k lines, Python 3.6 standard library only
- fog-of-war decision policy with BFS / DP / bounded local search
- offline JSONL harness, 25 tests, CI on Python 3.8-3.12
```

## 6. 如果用户名或仓库名不一样

```powershell
# 改远程地址
git remote set-url origin https://github.com/<你的用户名>/<仓库名>.git

# 全局替换 README 里的 owner/repo（PowerShell）
(Get-Content README.md -Raw) -replace 'xii-pm/commander2-ai','<你的用户名>/<仓库名>' |
  Set-Content README.md -Encoding UTF8
```

需要同步替换的位置：`README.md` 的 CI Badge 两处、`README.md` 末尾 BibTeX 的 `url`。
`docs/PUBLISH.md` 里的示例命令可以不改（它只是示例）。

## 7. 推送后验证清单

- [ ] 仓库首页 README 正常渲染，中文不乱码，Mermaid 图能显示
- [ ] **Actions** 标签页里 CI 是绿色（首次推送会自动跑，约 1 分钟）
- [ ] 语言统计显示 Python 99%+（说明没有把二进制塞进去）
- [ ] 右侧 License 显示 MIT
- [ ] 仓库文件里**没有** `__pycache__/`、`bfs-trace.jsonl`、`.zip`（`docs/` 里的路演 PPT 是刻意保留的）
- [ ] 点开 `docs/MODULES.md`、`docs/PARAMETERS.md` 正常
- [ ] 在 GitHub 仓库设置里加 Topics：`python`、`ai`、`game-ai`、`hex-grid`、
      `commander2`、`competition`、`reinforcement-learning`（虽然没用 RL，可去掉）
- [ ] 有需要的话，打 tag：`git tag -a v1.0.0 -m "ISCIIA 2026 submission" && git push --tags`

## 8. 之后想改：私有化 / 删库 / 清历史

```powershell
# 改成私有：GitHub → Settings → General → Danger Zone → Change visibility
# 删库：Settings → General → Delete this repository

# 如果误提交了敏感文件，需要从历史里彻底清除（先装 git-filter-repo）
pip install git-filter-repo
git filter-repo --path 误提交的文件 --invert-paths
```

## 9. 常见错误对照表

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `fatal: unable to access ... Failed to connect` | 直连被墙/代理没配 | 第 4.1 或 4.2 |
| `Support for password authentication was removed` | 用了账号密码 | 改用 Token 或 SSH |
| `remote origin already exists` | 已加过远程 | `git remote set-url origin <新地址>` |
| `rejected ... non-fast-forward` | 远程仓库非空（勾了 README） | `git pull --rebase origin main` 再推 |
| `LF will be replaced by CRLF` | Windows 换行转换 | 已用 `.gitattributes` 统一为 LF，可忽略警告 |
| `file is 123 MB; exceeds GitHub's limit` | 大于 100 MB | 本仓库不会有；别把 zip/PPT 拖进去 |
| 中文路径报错/乱码 | 某些 Git 版本/工具对中文路径处理差 | 已把仓库放在 `您说的队-github`，如仍报错可临时改为英文路径再推 |
| `Permission denied (publickey)` | SSH key 没配好 | 确认公钥已加到 GitHub，`ssh -T git@github.com` 测试 |

## 10. 发布前最后一遍合规自查

1. **代码来源**：`PROVENANCE.md` 已说明哪些模块迁移自队伍自训对手；确认与比赛规则
   不冲突（有些赛事要求参赛代码不得含第三方实现）。
2. **不含主办方资源**：SDK、地图、回放、PPT 截图、校徽都不要进仓库——本目录已经排除。
3. **许可证**：`LICENSE` 是 MIT，版权人写的是"伍家齐 and 您说的队"。若要改成
   个人或组织名义，直接改第一行。
4. **README 里的成绩表述**：确认"一等奖"表述与官方公示一致；如尚未公示，建议先
   用 Private 仓库，公示后再转 Public。
