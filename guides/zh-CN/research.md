# 模型研究与评估

[English](../research.md) · [简体中文](research.md) · [日本語](../ja/research.md)

NarraLoom 将模型职责分开暴露，因此你可以在保持故事游戏系统其余部分固定的情况下更改一个模块。有用的比较包括规划器准确性、NPC 声音、叙述一致性、内容生成质量和决策成本。

## 定义比较

1. 选择一个任务和一个模块。保持世界/故事修订、提示、规则、初始状态和其他模块设置固定。
2. 保存基线配置，并通过 `providers` 和 `bindings` 绑定候选，或注册一个 Python 引擎。
3. 运行契约测试，然后运行模型支持的工作流。将失败输出、修复、延迟和报告的 token 使用量记录为结果的一部分。
4. 使用留出案例评估新输入。使用独立游玩过程进行主观写作和可玩性判断。

按模块的追踪记录请求的模型、响应模型、部署修订标签、延迟和使用量。提供方修订标签是由实验者提供的元数据。原始诊断可能包含故事提示和秘密；在分享前选择并匿名化数据。

## 用固定输入评测模块

通过 `python -m pip install '.[research]'` 安装研究扩展。先保存一份模型输入，再用不同配置运行同一组任务：

```bash
python examples/make_evaluation_cases.py --output outputs/evaluation/cases.jsonl
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/baseline.local.json --output outputs/evaluation/baseline
narraloom evaluate --cases outputs/evaluation/cases.jsonl \
  --models-config configs/candidate.local.json --output outputs/evaluation/candidate
narraloom compare outputs/evaluation/baseline/report.json \
  outputs/evaluation/candidate/report.json --output outputs/evaluation/comparison.json
```

示例包含中、英、日三种语言的十二个任务。规划结果按明确断言自动计分；NPC 对话和旁白保留供人工评价。同一接口支持生成模块、System One 决策和自定义 Python 引擎。预期答案与模型请求、修复提示分别保存。

报告保留失败、修复次数、耗时、服务商返回的 token 用量及用量缺失情况。`--resume` 保留已有结果，继续尚未执行的任务。[评测接口文档](../../docs/EVALUATION.md) 介绍用例格式、指标、恢复方式和自定义适配器。

## 决策模型

```bash
python scripts/evaluate_decisions.py   --url http://127.0.0.1:18110/v1   --model YOUR_DECISION_MODEL   --revision YOUR_REVISION   --output outputs/validation/decision-comparison
```

包含的诊断集有 42 个编写的中文/英文案例，每个案例都以反转的退出顺序重复。报告包括有效响应、端到端准确性、Brier 分数、校准分箱、自动覆盖率/错误、顺序敏感性和延迟。为阈值选择创建一个单独的数据集，并为报告创建一个留出集。

`python scripts/evaluate_generation_router.py --output outputs/validation/generation-comparison` 将配置的生成模型应用于相同的路由输入。其分类结果支持准确性/延迟/token 比较；生成响应不提供校准概率。

## 端到端行为

```bash
python scripts/verify.py --distribution
python scripts/check_distribution.py --output outputs/validation/sdk-model-check   --sdk-live --live-models-config configs/models.local.json --secrets-root secrets
```

实时安装包检查会创建一个世界和两个故事，运行它们的自动测试，进行一个回合，恢复备份，并验证重启后的请求恢复。`scripts/check_longrun.py` 会执行更长的动作序列；检查其参数以了解场景和输出目录。

确定性重放检查事件/持久化行为。契约夹具隔离软件边界。实际模型检查在已执行任务上测量所选模型。在评估对话、能动性和故事质量时，将它们与人工评估结合使用。[Testing](../../docs/TESTING.md) 列出了重点测试套件；[engine contracts](../../docs/ENGINES.md) 描述了追踪和适配器。
