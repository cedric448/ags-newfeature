# 测试决策记录（与用户确认）

确认时间：2026-09-19

## 决策项

| # | 议题 | 决策 |
|---|---|---|
| 1 | 北京地域沙箱启动失败 | 需先创建 AGS tool template，镜像仓库使用 **TCR 实例 `tcr-mvlaq1sq`**；用户名 `100000881922`；密码为提供的 TCR token（长 JWT，见下） |
| 2 | 模板快照 / 沙箱快照 | **暂缓**（公开文档与 SDK 均无 Snapshot 接口） |
| 3 | AgentBucket / AgentCFS 资源 | 用户尚未准备 → **由我输出控制台创建指导**，用户按指导创建后回填参数 |
| 4 | WAA / OSWorld | **先跳过**，只做轻量测试例 |

## 因此的测试范围

**做：**
- TC-01 基线：TCR 镜像 + 沙箱工具/实例启动打通
- TC-02 AgentBucket 使用
- TC-03 AgentCFS 使用
- TC-04 Agent Engine（弹性部署）
- 横切用例：网络模式、生命周期、超时、认证、幂等、清理

**暂缓：**
- 模板快照（等用户明确功能形态）
- 沙箱快照（同上）
- WAA 沙箱（重依赖）
- OSWorld 沙箱（重依赖）

## TCR 凭据（敏感，勿入 Git）

```
TCR 实例:   tcr-mvlaq1sq
用户名:     100000881922
密码/token: <TCR_ACCESS_TOKEN —— 见本地 .env 的 TCR_PASSWORD，勿提交>
openerUin:  100008634787
exp:        2105159103 (~2036)
```

对应地域：`ap-beijing`
