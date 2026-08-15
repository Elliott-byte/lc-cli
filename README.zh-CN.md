# lc — 终端里的 LeetCode

[English](README.md) · **简体中文**

浏览题目、阅读题面、用自己的编辑器写题，然后直接提交到 LeetCode 的真实判题机——全程不离开 shell。

```
lc                              # 全屏浏览器：选题、编辑、测试、提交
lc list --difficulty medium --status todo
lc pick 322 --lang python3      # 生成 ~/leetcode/0322-coin-change/solution.py 并打开
lc test                         # 在 LeetCode 判题机上跑样例
lc submit                       # 正式提交
```

![全屏浏览器](docs/tui.svg)

![lc test 在真实判题机上运行](docs/test.svg)

## 安装

```bash
brew install elliott-byte/tap/lc-cli
# 或者用 uv：
uv tool install git+https://github.com/Elliott-byte/lc-cli
```

从本仓库的 checkout 安装：

```bash
uv tool install .
```

改动源码后重新执行一次（如果你的环境支持 `.pth` 文件，也可以用
`uv tool install -e .` ——部分沙盒环境会忽略它们）。

想参与开发的话，用本地 venv：

```bash
uv venv && uv pip install -e '.[dev]' && .venv/bin/python -m pytest
```

## 登录

`lc` 以你的身份访问 leetcode.com，用的是浏览器里的会话 cookie。

```bash
lc login
```

会直接从本机浏览器（Chrome、Firefox、Safari、Edge 等）读取并验证。还没登录？
它会打开 LeetCode 登录页——在那里登录，回车，`lc` 就能拿到新 cookie。macOS
上系统可能会为浏览器的 cookie 存储弹一次钥匙串授权；读取 Safari 的 cookie
需要给终端 App 完全磁盘访问权限。

如果没有任何浏览器存储可读（远程机器、小众浏览器）：

```bash
lc login --paste                 # 从 DevTools → Application → Cookies
                                 # 复制 LEETCODE_SESSION 和 csrftoken
lc login --session … --csrf …    # 脚本化
```

Cookie 以 `0600` 权限写入 `~/.lc/cookies.json`；不想落盘的话也可以通过
`$LEETCODE_SESSION` / `$LEETCODE_CSRF` 环境变量提供。

会话每隔几周会过期——重新 `lc login` 一次即可。

## WSL

以上一切在发行版内原样可用——用同一条 `uv tool install` 安装，TUI、判题和
vim 插件的行为与任何 Linux 相同。跨越 Windows 边界的部分都处理好了：网页通过
Windows 侧浏览器打开（`explorer.exe`，装了 wslu 则用 `wslview`）；`lc login`
直接穿过 `/mnt/c` 读取 Windows Firefox 的配置文件，Firefox 用户自动登录。
Windows 的 Chrome 和 Edge 用只有浏览器自己能解开的密钥加密 cookie
存储——浏览器之外谁也读不了——所以在那里用 `lc login --paste` 登录；登录流程也会提示你。

## 命令

![lc list](docs/list.svg)

| 命令 | 作用 |
| --- | --- |
| `lc list [关键词]` | 浏览题库。`-d easy`、`-t "Two Pointers"`、`-s todo`、`--free` |
| `lc show 322` | 打印题面，按终端排版 |
| `lc pick 322 -l go` | 从起始代码生成解题文件并打开 `$EDITOR` |
| `lc edit 322` | 重新打开已有的解题文件 |
| `lc test` | 在 LeetCode 判题机上跑样例 |
| `lc submit` | 提交；打印判定、运行时间和击败百分比 |
| `lc daily` | 今天的每日一题（`--pick` 直接开做） |
| `lc random -d medium` | 随机抽一道没做过的题 |
| `lc review` | 间隔重复刷题本（`add` / `rm` / `level` / `postpone`） |
| `lc review sync` | 和你的 git 仓库同步刷题本（也有 `pull` / `push`） |
| `lc stat` | 按难度统计你的解题数 |
| `lc history 322` | 某题的最近提交记录 |
| `lc code` | 高亮打印当前解答 |
| `lc tags` | 话题标签，按题目数排序 |
| `lc sync` | 刷新本地题目索引 |
| `lc setup vim` | 安装 Vim 快捷键（`\t` 测试，`\s` 提交） |
| `lc tui` | 全屏浏览器（直接敲 `lc` 也一样） |

`lc test`、`lc submit`、`lc code`、`lc edit` 和 `lc history` 在题目目录里
运行时不用带参数——它们会从 `.lc.json` 里读。

判定失败时二者都以非零退出，所以可以直接和 shell 脚本组合：

```bash
lc test && lc submit -y
```

## 工作区结构

```
~/leetcode/
  0322-coin-change/
    README.md      题面（Markdown）
    solution.py    起始代码 + 你的解答
    .lc.json       这个目录对应哪道题、什么语言
```

整个解题文件都会被提交。`lc` 写入的文件头是目标语言的注释，判题机会忽略它。

## 配置

设置保存在 `~/.lc/config.json`，用 `lc config …` 或 TUI 的设置页修改——见
[设置页](#设置页)。设 `$LC_HOME` 可整体挪走这个目录。题目索引和题面缓存在
`~/.lc/cache.db`——随时可以删，`lc` 会重建。

## Vim

```bash
lc setup vim
```

往 `~/.vim/plugin/lc.vim` 放一个小插件——不改 `.vimrc`，删掉文件即卸载。
如果还没配置过编辑器，它还会顺手执行 `lc config editor vim`，让 `lc pick`
直接进入 Vim。

在解题 buffer（`.lc.json` 旁边的任何文件）里，普通模式：

| 按键 | 作用 |
| --- | --- |
| `\t` | 保存，然后 `lc test` |
| `\s` | 保存，然后 `lc submit` |
| `\p` | 在左侧分屏显示/隐藏题面 |
| `\o` | 在浏览器打开题目页（图片动画在那边看） |
| `\m` | 把这道题存进刷题本 |
| `\q` | 全部保存，然后退出 Vim——回到 TUI/shell |

打开解题文件时题面会自动出现在旁边——`\p`（或在面板里按 `q`）隐藏，`\p`
再唤回。想手动控制就在 vimrc 里加 `let g:lc_auto_statement = 0`。
在代码窗口直接 `:q` 也不会把你困在题面面板里：面板作为最后一个窗口时会
带着 Vim 一起退出——从 TUI 进来的话，此刻你已经回到题目列表了。

只要你的 Vim 带 `+terminal`（或用 Neovim），这个面板显示的就是完整渲染的
题面——一个小终端分屏里跑 `lc show`，颜色、示例框、上标和 CLI 里一模一样。
不支持的编辑器回退到目录里的原始 `README.md`；`let g:lc_statement_render = 0`
可强制所有情况都用纯文件。

Python 解题 buffer 会保持空格缩进：Tab 键输出空格，粘贴进来的真 Tab
在保存时被转换。LeetCode 的起始代码用空格缩进，判题机对一个混入的 Tab 直接报
`TabError`——实在需要的话 `let g:lc_python_indent = 0` 可以关闭。

快捷键从文件自己的目录执行，所以在哪里启动的 Vim 无所谓。它们用
`<leader>`，默认是反斜杠。升级 `lc` 之后重新跑一次 `lc setup vim --force`
刷新插件；Neovim 用户把同一个文件复制到 `~/.config/nvim/plugin/`。

## TUI

直接敲 `lc`（或 `lc tui`）打开双栏浏览器：左边题目列表，右边题面。左栏还有
第二个标签页——刷题本（见下一节），按 `tab` 来回切换。新机器上它会自己下载
题目索引。节奏是：移到一道题，`enter` 在编辑器里打开，写完退出编辑器回到
列表，`r` 跑样例，`s` 提交——循环往复。对已经开始的题按 `enter` 会重新打开
你已有的文件。

今天的每日一题用黄色 `★` 置顶（应用打开时默认选中），当天的题永远只差一次
按键；任何时候按 `D` 都能跳回去。

✔/✗ 标记会自己保持新鲜：从编辑器回来时会重读本地索引，在 Vim 里 `\s`
提交的结果立刻可见；`ctrl+r` 随时手动刷新（本地即时，不同于会重新下载索引的
`R`）。所有刷新都会把光标留在原来的题上。

| 按键 | 作用 |
| --- | --- |
| `↑` `↓` | 在列表中移动 |
| `/` | 过滤（`esc` 或 `enter` 回到列表） |
| `enter` / `p` | 生成解题文件并打开编辑器 |
| `r` | 跑样例 |
| `s` | 提交 |
| `tab` | 在题目列表和刷题本之间切换 |
| `m` | 把当前题存进刷题本 |
| `d` | 切换难度过滤 |
| `t` | 切换状态过滤 |
| `o` | 在 leetcode.com 打开该题 |
| `D` | 跳到今天的每日一题 |
| `c` | 设置页（工作区、语言、编辑器、曲线、刷题本仓库） |
| `g` | 把刷题本同步到 git（Review 页） |
| `ctrl+r` | 从本地索引刷新列表 |
| `R` | 重新同步题目索引 |
| `q` | 退出 |

## 刷题本（间隔重复）

有的题值得见第二次、第五次。按 `m` 把光标下的题存进 **Review** 标签页，
它会沿艾宾浩斯记忆曲线升级：1 级 1 天后再见，然后 2、4、7、15 天——经典的
复习阶梯，一路延伸到 10 级的一年。有题到期时标签页会直接写出来：`Review (3)`，到期的题排在最上面。

![刷题本](docs/review.svg)

复习自动记分：把题重做一遍然后提交。到期的题提交通过就升一级，提交失败
就掉回 1 级、间隔重新开始。在哪提交都算——TUI 里、shell 里的 `lc submit`、
Vim 里的 `\s`。没到期就又做了一遍只算练手，排期不动。

Review 页里：`+`/`-` 手动调级（从今天起重新排期），`z` 把一道题推到明天，
`Z` 推掉今天所有到期的题，`x` 移除，`g` 和 git 仓库同步，`enter` 照常在
编辑器里打开。在 Vim 里写题写到一半，`\m` 直接把当前这道题存进去。

同一个刷题本在 shell 里：

```bash
lc review                  # 整个刷题本，最先到期的在前
lc review add 322 -l 3     # 手动保存，从 3 级起步
lc review add              # ……或者就存你正待着的这个题目目录
lc review postpone         # 今天不想刷——到期的全推到明天
lc review rm 322
```

## 设置页

在 TUI 里按 `c` 打开设置页：工作区、默认语言、编辑器、刷题本仓库和记忆
曲线，边打字边预览这条曲线的含义（`6 levels: lv1→1d · lv2→2d · lv3→4d …`）。
`ctrl+s` 保存，`esc` 取消。同样的设置在 shell 里：

![设置页](docs/config.svg)

```bash
lc config show
lc config lang go                  # `lc pick` 的默认语言
lc config workspace ~/code/leetcode
lc config editor "code -w"         # 不设则用 $EDITOR / $VISUAL
lc config curve 1,2,4,7,15,30      # 六级，起步更缓
lc config curve reset              # 回到默认的艾宾浩斯曲线
lc config repo git@github.com:you/lc-review.git
```

曲线随你定——每级一个间隔（单位天），条目数就是级数。

## 跨机器同步刷题本

指一个你自己的 git 仓库给 lc，刷题本就跟着你走：

```bash
lc config repo git@github.com:you/lc-review.git
lc review sync             # 拉取、合并、推送（或在 Review 页按 g）
lc review pull             # 只把仓库里的刷题本拉下来
lc review push             # 只把本机的刷题本推上去
```

配好仓库后，Review 页底部会有一条状态栏，不用敲命令就知道自己的同步状态：

| 显示 | 含义 |
| --- | --- |
| `✔ synced 2h ago` | 刷题本和仓库一致（截至上次同步） |
| `↑ 3 changes to push · synced 2h ago` | 之后又改过，有 3 处待推送 |
| `○ not synced yet — press g` | 配好了但还没同步过 |
| `✗ last sync failed: …` | 上次同步失败，并说明原因 |

它只读本地文件算出来——刷新列表永远不会去连网络——所以"synced"的意思是
"上次通信时和仓库一致"，而不是"刚查过 GitHub"。没配仓库时这条整个不显示。

除非你有 GitHub 认可的 SSH key，否则用 `https://` 开头的地址——只要 `gh`
登录过，https 开箱即用。同步失败时会说明原因和下一步该做什么（比如
`GitHub rejected this machine's SSH key` → 换 https 地址，或 `gh ssh-key add`）。

lc 在 `~/.lc/review-repo` 保留一个私有克隆，往仓库里写两个文件：
`review.json`（它读回来的刷题本）和 `REVIEW.md`（同一份数据的带链接表格，
GitHub 上直接可读）。它**不会**写 `README.md`，所以指向一个已有 README 的
仓库也是安全的。

合并在 lc 里做，不在 git 里——你永远不会被要求解决冲突。两边取并集，同一道题
两边都有时，**最后改动的那份**胜出：每次改动都会盖一个 UTC 时间戳，所以两台
机器在同一天操作也能正确定序。删除同样会传播——移除一道题会留下一个墓碑，
墓碑也是一次改动，于是另一台机器跟着删掉，而不是把题还回来。被删掉的题重新
加入会从 1 级复活。

两台机器同时推送时会有一方被拒绝，lc 会自己重做一次同步，你不会看见。

刷题本是用户数据，存在 `~/.lc/review.json`，特意不放进缓存——删掉
`cache.db` 不会碰到它。

## 备注

- Accepted 有烟花——`lc test` 一组小的，`lc submit` 四连发大的；失败则是一个
  小人缓缓跪地（orz），提交失败时头顶还会飘来一朵乌云下雨。管道和脚本里
  自动跳过，`LC_NO_FX=1` 全局关闭。
- 付费题需要会员账号；`lc` 会明确说明，而不是奇怪地失败。
- `lc test` 和 `lc submit` 跑在 LeetCode 的判题机上而非本地，判定和运行时间
  百分比都是真实数据。
- 请求以人类节奏发往 leetcode.com。脚本批量循环会触发限流；`lc` 会把它作为
  明确的错误报出来。
