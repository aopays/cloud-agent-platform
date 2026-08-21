# GitHub 发布检查清单

## 1. 本地门禁

- [ ] `.env`、虚拟环境、IDE 配置、日志、运行目录、产物和数据库未进入发布文件。
- [ ] 本地调试服务已经停止，项目 Docker 容器、网络和数据卷已按需清理。
- [ ] Ruff format/check、mypy、pytest、security marker、compileall 和 pip check 通过。
- [ ] `docker compose config --quiet` 在临时安全配置下通过。
- [ ] 应用镜像和 Sandbox 镜像成功构建。
- [ ] 应用 `/readyz`、首页、需求挖掘页和 API 文档可访问。
- [ ] Sandbox 动态验证非 root、禁网、只读根文件系统和资源限制。
- [ ] 常见 API Key、私钥和凭证模式扫描没有命中。
- [ ] 个人用户名、盘符绝对路径、私有仓库地址和真实任务内容扫描没有命中。

## 2. 公开内容复核

- [ ] README 的能力声明与实际代码一致，没有把目标多 Agent 架构写成已实现能力。
- [ ] LICENSE、SECURITY、CONTRIBUTING、Code of Conduct 和 Changelog 已确认。
- [ ] `.env.example` 只包含占位配置，不包含真实密钥。
- [ ] OpenAI API Key 只在服务端配置，不进入浏览器、日志、事件或产物。
- [ ] `SANDBOX_BACKEND=local` 的可信输入限制醒目标注。
- [ ] 已知生产缺口包括内存持久化、单 Token、无正式限流和强隔离验证。

## 3. 初始化 Git

当前工作目录需要由所有者确认发布文件后再初始化。不要使用 `git add .` 或 `git add -A`。

```powershell
git init -b main
git status --short
git add -- AGENTS.md README.md LICENSE SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md CHANGELOG.md
git add -- .gitignore .dockerignore .env.example pyproject.toml requirements.lock Dockerfile docker-compose.yml
git add -- .github docs examples migrations sandbox scripts src tests
git status --short
git diff --cached --check
```

暂存后再次确认没有 `.env`、`.venv`、`.idea`、`.runs`、`.artifacts`、日志、数据库或密钥。

## 4. GitHub 仓库设置

- [ ] 首次推送前确认仓库名称、所有者和 public/private 可见性。
- [ ] 默认分支为 `main`，禁止 force push 和删除。
- [ ] Pull Request 必须通过 CI、Security 和至少一次审查。
- [ ] 启用 Dependabot、Code scanning、Secret scanning 和 Push protection。
- [ ] 启用 Private vulnerability reporting。
- [ ] 不在仓库 Secret 中保存不需要的长期 OpenAI Key；演示使用独立项目和低额度 Key。
- [ ] Release 使用语义版本、Changelog 和不可变 tag。

## 5. 首次发布后验证

- [ ] 在全新的 Windows 和 Linux 环境各执行一次 README 快速开始。
- [ ] 从 `.env.example` 开始，只填写 `OPENAI_API_KEY` 后可以进入 `/discovery`。
- [ ] 离线 Demo 不调用 OpenAI，也不产生费用。
- [ ] GitHub Actions 全部通过，无被忽略的 High/Critical 告警。
- [ ] 使用无权限测试账号确认 README、文档和下载链接公开可访问。
