# GitHub App Public 管理注意事项

本文档记录 `cnb-organization` 管理 GitHub App 公开安装时的安全边界。当前管理组织的 GitHub login 仍是 `cnb-workspace`，显示名是 `cnb-organization`。

## 基本原则

- Public GitHub App 只是允许其他账号安装；它不自动获得我们的仓库权限。
- 真正的权限边界必须在 cnb 自己的服务端/脚本里实现，不能只依赖 GitHub UI 上的权限描述。
- 所有 installation 默认拒绝，只有 allowlist 中明确登记的账号、仓库、installation 才能执行动作。
- App 安装时尽量选择 `Only select repositories`，不要默认给 `All repositories`。
- 权限从最小集开始；需要写 issue/comment 时只给 issues write，需要写 PR 时再给 pull requests write。

## 当前 App

- App: `cnb-workspace-musk`
- App URL: `https://github.com/apps/cnb-workspace-musk`
- App ID: `3660379`
- 管理组织内已安装 installation: `130989940`
- 当前允许的管理仓库: `cnb-workspace/cnb`
- canonical 仓库 installation: `130997703`
- 当前允许的 canonical 仓库: `ApolloZhangOnGithub/cnb`
- 可见动作验证: `https://github.com/ApolloZhangOnGithub/cnb/issues/65#issuecomment-4414136928`

## Public 前检查

公开 App 前必须确认：

- `~/.github-apps/cnb-workspace-musk/allowlist.json` 存在。
- allowlist 使用 `default_action: "deny"`。
- allowlist 不允许 repository wildcard，例如不能写 `owner/*`。
- 未知账号、未知仓库、未知 installation 必须被拒绝。
- 对尚未拿到真实 `installation_id` 的目标，只能用短期 `expires_at` 临时登记。
- webhook handler 或 token minting 脚本必须先调用 guard，再生成 installation token。

当前本地 guard 命令：

```bash
python -m lib.github_app_guard validate --app cnb-workspace-musk
python -m lib.github_app_guard check --app cnb-workspace-musk --repository cnb-workspace/cnb
```

## Public 后流程

1. 通过安装链接安装 App 到目标账号或组织。
2. 安装时只选择目标仓库，例如 `ApolloZhangOnGithub/cnb`。
3. 安装完成后立刻记录真实 `installation_id`。
4. 更新 allowlist，把临时未绑定规则改成绑定真实 `installation_id` 的规则。
5. 再执行 App 可见动作，例如 issue comment、check run 或 PR comment。
6. 对非 allowlist installation 的 webhook 只记录并忽略，不生成 token，不调用 GitHub 写接口。

## 禁止事项

- 不要因为 App 是 public 就响应所有 installation。
- 不要在 guard 之前生成 installation token。
- 不要使用宽泛仓库匹配。
- 不要把 private key、webhook secret、installation token 写进仓库。
- 不要用真实公众人物头像制造官方身份混淆；如需角色化头像，应使用明显非官方的风格化图片。
