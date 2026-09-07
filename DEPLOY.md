# A股量化分析系统 - Render.com 部署指南

## 一、准备工作

### 1. 注册 GitHub 账号
- 访问 https://github.com 注册账号（免费）
- 记住你的用户名（后面会用到）

### 2. 注册 Render.com 账号
- 访问 https://render.com
- 点击 "Get Started" 或 "Sign Up"
- 选择用 GitHub 账号登录（最方便）
- 完成注册

## 二、上传代码到 GitHub

### 方法一：用命令行（推荐）

在电脑终端执行以下命令（把 `你的用户名` 替换成你的 GitHub 用户名）：

```bash
cd ~/quant_simple

# 初始化 git 仓库
git init
git add .
git commit -m "初始提交：A股量化分析系统"

# 在 GitHub 上创建仓库后，执行以下命令上传
# （先在 GitHub 网页上创建一个名为 a-share-quant 的空仓库，不要勾选 README）
git remote add origin https://github.com/你的用户名/a-share-quant.git
git branch -M main
git push -u origin main
```

### 方法二：用 GitHub Desktop（图形界面）
1. 下载安装 GitHub Desktop：https://desktop.github.com
2. 登录 GitHub 账号
3. 点击 "Add" → "Add Existing Repository"
4. 选择 `~/quant_simple` 文件夹
5. 点击 "Publish repository" 上传到 GitHub

## 三、在 Render.com 上部署

### 1. 创建 Web Service
1. 登录 https://render.com
2. 点击右上角 "New +" → "Web Service"
3. 选择你刚上传的 GitHub 仓库（a-share-quant）
4. 点击 "Connect"

### 2. 配置服务
填写以下配置：

| 配置项 | 值 |
|---|---|
| Name | a-share-quant（随便起） |
| Region | Singapore（新加坡，离国内近） |
| Branch | main |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
| Instance Type | Free（免费） |

### 3. 配置环境变量（可选）
在 "Environment" 选项卡中添加：

| Key | Value |
|---|---|
| PYTHON_VERSION | 3.11.7 |

### 4. 部署
点击 "Create Web Service"，Render 会自动开始构建和部署。

部署过程大约需要 2-5 分钟，看到 "Live" 就表示部署成功了。

## 四、访问

部署成功后，Render 会给你一个网址，类似：
```
https://a-share-quant.onrender.com
```

用手机或电脑浏览器打开这个网址就能使用了，不需要连同一个WiFi，手机用4G/5G也能访问。

## 五、注意事项

### 免费版限制
1. **休眠**：15分钟没有请求会自动休眠，第一次打开需要等10-30秒冷启动，之后就快了
2. **SQLite数据**：重新部署时自选股数据会丢失（日常使用不会丢失）。可以定期备份，或者把自选股导出
3. **每月750小时**：免费版每月750小时运行时间，足够24小时不间断运行
4. **512MB内存**：足够运行这个系统

### 防止休眠（可选）
用免费监控服务每5分钟访问一次，防止休眠：
- 访问 https://uptimerobot.com 注册
- 添加一个 HTTP 监控，网址填你的 Render 网址
- 设置每5分钟监控一次

### 绑定自定义域名（可选）
如果有自己的域名，可以在 Render 的 "Custom Domains" 里绑定，Render 会自动配置 HTTPS。

## 六、更新代码

以后修改了代码，只需要：
```bash
cd ~/quant_simple
git add .
git commit -m "更新说明"
git push
```
Render 会自动检测到 GitHub 更新并重新部署。

## 常见问题

**Q: 部署失败怎么办？**
A: 看 Render 的日志，常见问题：
- requirements.txt 里的包版本不兼容 → 去掉版本号试试
- 端口配置错误 → 确保用 `$PORT` 环境变量
- 内存不足 → 升级实例类型

**Q: 自选股数据丢失了怎么办？**
A: 免费版重新部署会清空数据。可以在设置里导出自选股，重新部署后再导入。

**Q: 国内访问慢怎么办？**
A: 可以用 Cloudflare 免费CDN加速，或者选择新加坡/日本区域。
