# dy-download

Windows 抖音主页批量下载工具。粘贴用户主页链接后，先解析作品列表，再按视频 / 图文筛选并勾选下载。

当前版本：**v1.0.0**

## 主要功能

- 抖音用户主页解析
- 真实浏览器 + Cookie 登录态解析，自动滚动主页抓取作品
- 视频 / 图文识别
- 作品列表预览
- 按类型、标题关键词筛选
- 全选 / 取消全选 / 自由勾选
- 批量下载勾选作品
- 无水印资源由上游下载核心优先选择
- 图集图片下载
- 浏览器登录自动获取 Cookie
- 支持手动粘贴 Cookie
- SQLite 去重与已有文件跳过
- 浏览器兜底
- 下载并发设置
- 保存目录记忆
- 完整运行日志
- Windows 打包脚本

## 为什么不用邀请码

`dy-download` 不调用 Douzy 桌面客户端，也不修改或绕过其邀请码系统。

底层下载能力使用 MIT 开源项目：

- `jiji262/douyin-downloader`

首次运行时由本工具拉取公开源码并安装依赖，因此整个下载流程不依赖 Douzy 的内测账号或邀请码。

## 主页解析方式

很多旧项目的问题不是“下载不了”，而是抖音主页接口一变，连作品列表都拿不到。

本项目 v1.0 的主页列表采用另一条路径：

1. 使用当前 Cookie 打开真实抖音用户主页；
2. Playwright 监听页面实际发出的作品请求；
3. 自动向下滚动主页；
4. 从响应中的 `aweme_list` / `items` 收集作品；
5. 在 GUI 中显示视频、图文、标题、发布时间、点赞、评论、图片数量等；
6. 用户勾选后，把单条视频 / 图文链接交给成熟下载核心。

这样主页“列表解析”和“媒体下载”是分离的，某一边发生变化时更容易单独修复。

## Windows 使用方法

### 环境要求

当前 v1.0 源码版需要：

- Windows 10 / 11
- Python 3.10+
- Git

### 启动

双击：

```text
start.bat
```

或者：

```bash
python -m pip install -r requirements.txt
python app.py
```

### 第一次使用

1. 打开软件，进入 **环境与 Cookie**。
2. 点击 **安装/更新下载核心**。
3. 等待 Python 依赖和 Playwright Chromium 安装完成。
4. 点击 **浏览器登录获取 Cookie**。
5. 在打开的浏览器中登录抖音，按上游工具提示完成保存。
6. 回到 **主页下载**。
7. 粘贴完整主页链接，例如：

```text
https://www.douyin.com/user/MS4wLjABAAAA...
```

8. 点击 **① 解析主页**。
9. 浏览器会打开主页并自动滚动。若出现安全验证，请人工完成。
10. 解析完成后，在列表中筛选并勾选作品。
11. 点击 **② 下载勾选作品**。

## 手动 Cookie

如果自动获取 Cookie 不方便：

1. 在浏览器登录抖音；
2. F12 → Network；
3. 打开任意 `douyin.com` 请求；
4. 在 Request Headers 中复制完整 `Cookie`；
5. 软件 → **环境与 Cookie** → **手动填写 Cookie**；
6. 粘贴并保存。

Cookie 只保存在本机 `.runtime/config.yml`，`.runtime/` 已加入 `.gitignore`。

## 项目结构

```text
dy-download/
├─ app.py                       # PySide6 GUI
├─ backend.py                   # GUI 与上游核心桥接
├─ scan_profile.py              # Playwright 真实主页扫描
├─ bootstrap_backend.py         # 拉取/更新开源下载核心及依赖
├─ requirements.txt
├─ start.bat                    # 源码版一键启动
├─ build.bat                    # Windows PyInstaller 打包
├─ .github/workflows/
│  └─ build-windows.yml         # 自动检查与 Windows 构建
├─ .runtime/                    # Cookie / 扫描缓存 / SQLite（自动生成）
└─ vendor/
   └─ douyin-downloader/        # 上游开源核心（首次安装生成）
```

## 打包

运行：

```text
build.bat
```

输出：

```text
dist/dy-download/dy-download.exe
```

> v1.0 的 EXE 是 GUI 打包版本，下载核心仍通过系统 Python 与 Git 安装和运行。因此目标电脑仍需 Python 3.10+ 与 Git。后续版本可以再做真正的全内置单机发行包。

## 数据目录

运行后主要生成：

```text
.runtime/config.yml       # Cookie 与运行配置
.runtime/scan.json        # 最近一次主页解析列表
.runtime/dy_downloader.db # 去重数据库
vendor/                   # 上游核心
```

这些内容不会提交到 GitHub。

## 当前边界

- 仅针对公开且当前账号有权访问的作品。
- 抖音出现验证码 / 安全验证时，需要在浏览器中人工完成。
- 抖音随时可能调整页面和接口，扫描器与上游核心都可能需要跟随更新。
- 作品列表目前不做封面图片在线预览，优先保证主页解析与批量下载稳定。
- 当前主要面向 Windows 10/11。

## 上游许可

`jiji262/douyin-downloader` 使用 MIT License。`dy-download` 不包含或破解 Douzy 的邀请码授权逻辑，仅使用公开开源代码路径。

## 使用说明

请只保存和使用你有权下载的内容，并遵守平台规则、著作权规则和当地法律。
