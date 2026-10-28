# Secret scanning and redaction

提交前执行：

```bash
gitleaks detect --no-banner --redact
git grep -n -I -E "(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----)" -- . ':!*.lock'
```

本项目允许的配置示例只使用空值或本地占位：

```dotenv
DATABASE_URL=sqlite:///./agent_platform.db
ANTHROPIC_API_KEY=
```

不要提交真实 token、云端 URL、Cookie、用户资料、完整业务剧本、数据库 dump 或本地绝对路径。`Artifact`、SQLite 文件、`.env` 和本地导出目录默认被 `.gitignore` 排除。
