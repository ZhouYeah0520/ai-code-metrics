# AI Code Metrics

一个面向研发效能练习的 Python CLI：标记 AI 辅助提交、通过 Git notes 保存可审计的变更行数、按提交范围统计新增行占比，并提供 Claude Code / Codex CLI 的可选调用适配器。

## 快速开始

要求 Python 3.10+ 和 Git。无需第三方 Python 依赖。

```powershell
cd ai-code-metrics
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m ai_code_metrics --help
python -m ai_code_metrics mark --commit HEAD --tool manual
python -m ai_code_metrics ratio --since HEAD~5 --until HEAD
python -m ai_code_metrics list --since HEAD~5 --until HEAD
```

`mark` 将该提交相对于第一父提交的新增/删除行数写入 `refs/notes/ai-code-metrics`。`ratio` 对指定范围逐提交汇总，避免把 `git diff HEAD`（工作区差异）误当成历史总量。二进制文件的行数由 Git 标为 `-`，不计入行数分母。合并提交不纳入 `ratio` 统计；范围内没有变更行时比率为 `null`。

自动 hook 是可选项：`python -m ai_code_metrics install-hook` 安装 `post-commit` hook；只有提交信息含 `[AI]` 才会记录标记。要共享 notes，需单独推送/拉取 notes ref：`git push origin refs/notes/ai-code-metrics`。

## CLI 适配器

安装 Claude Code 或 Codex CLI 并完成其各自登录后，可运行：

```powershell
python -m ai_code_metrics run --tool claude-code "解释当前仓库结构"
python -m ai_code_metrics run --tool codex "解释当前仓库结构"
```

调用设置超时，不启用 shell，并将结构化输出尽可能归一成文本。此功能会把 prompt 和当前目录发送给所选 CLI；运行前确认符合你组织的数据策略。单元测试使用假的子进程结果，不会调用模型或修改仓库。

真实调用还依赖 CLI 自身的登录、模型和 API 配置；适配器会把常见的认证、模型和服务错误转成非零退出码，即使某个 CLI 外层进程错误地返回 0，也不会被上层当成成功。

## 自动修复（实验）

`fix` 子命令进入「跑测试 → 让所选 CLI 修改 → 再跑测试」的多轮闭环，直到测试通过或达到轮次上限：

```powershell
python -m ai_code_metrics fix --tool claude-code --test "pytest -q" --rounds 5
```

该模式以编辑权限调用 CLI，会实际修改当前目录的文件，属有副作用的操作：请在可丢弃的仓库中运行，并确认编辑权限 flag 与本机 CLI 版本一致（`claude --help` / `codex --help`）。单元测试对子进程做了 mock，不会调用真实模型或修改仓库。

## 统计口径和限制

AI 辅助提交中的新增行数 / 范围内所有提交的新增行数。Git notes 是提交级标记，不是逐行作者证明；重写历史、冲突解决、未提交改动和后续人工编辑都会影响解释。此指标是透明的工程代理指标，不能据此断言每行代码由模型生成。notes 不会随普通分支 push 自动同步。

## 验证

`python -m unittest discover -s tests -v` 在 Python 3.10+ 执行。CI workflow 在 push 和 pull request 时运行同一测试集。
