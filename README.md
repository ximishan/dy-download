# dy-download

一个面向 Windows 的抖音主页批量下载工具。目标是把复杂的命令行操作简化成：粘贴主页链接 → 登录一次获取 Cookie → 批量下载视频/图文。

## 当前版本

v0.1.0 Demo

### 已实现

- Windows PySide6 图形界面
- 输入抖音用户主页链接
- 选择保存目录
- 设置下载数量，0 = 全部
- 设置并发线程
- 浏览器兜底开关
- 一键安装/更新 `jiji262/douyin-downloader` 开源核心
- 一键启动浏览器登录并获取 Cookie
- 使用主页 `post` 模式批量下载公开视频/图文
- SQLite 去重配置
- 自动保留已获取 Cookie
- Windows `start.bat` 启动入口

## 使用

### 1. 环境

建议：

- Windows 10 / 11
- Python 3.10+
- Git

### 2. 启动

双击：

```text
start.bat
```

或者：

```bash
pip install -r requirements.txt
python app.py
```

### 3. 首次运行

1. 点击 `安装/更新下载核心`
2. 等待依赖与 Chromium 安装完成
3. 点击 `浏览器登录获取 Cookie`
4. 在打开的抖音页面完成登录
5. 回到工具，输入目标用户主页
6. 点击 `开始下载主页作品`

## 目录说明

```text
dy-download/
├─ app.py                  # GUI
├─ backend.py              # 下载核心桥接与配置
├─ bootstrap_backend.py    # 自动安装/更新开源核心
├─ requirements.txt
├─ start.bat
├─ .runtime/               # Cookie、配置、SQLite，运行后生成，不提交 Git
└─ vendor/                 # 上游下载核心，运行后生成，不提交 Git
```

## 技术方案

GUI 不使用 Douzy 桌面版，也不依赖邀请码系统。

当前底层通过 MIT 开源项目：

- https://github.com/jiji262/douyin-downloader

首次安装时自动拉取其源码，并使用它现有的主页解析、无水印资源选择、图文下载、Cookie 获取和浏览器兜底能力。

## 下一步

- [ ] 将“安装核心”改成首次启动自动完成
- [ ] GUI 中直接显示 Cookie 状态
- [ ] 增加手动 Cookie 编辑入口
- [ ] 先解析主页并显示作品总数/视频数/图文数
- [ ] 作品列表预览与勾选下载
- [ ] 下载进度、速度、成功/失败统计
- [ ] 下载历史与增量下载界面
- [ ] 打包成独立 Windows EXE
- [ ] 减少用户本机对 Python/Git 的依赖
- [ ] 评估后续将必要上游模块合法内置，避免首次运行联网拉取源码

## 说明

请仅下载你有权保存和使用的公开内容，并遵守平台规则与相关法律法规。
