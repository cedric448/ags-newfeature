AGS 暂停恢复、Snapshot 与 Fork 功能性能验证报告

日期：2026-08-12
地域：上海（ap-shanghai）
沙箱工具：sdt-d5y3dz8u（swe-rl-snapshot-test）
规格：1 CPU / 1 GiB / 10 GiB 系统盘
镜像：isaac-test.tencentcloudcr.com/swe_rl/swe-rl-sandbox:envd-v0.6.13
COS：swe-rl-tracing-1258272081
---
1. 测试范围和口径
1.1 暂停恢复 Barrier 基准
参考 scenario-pause-matrix.js：
- MAX_VUS=10
- CREATE_BUDGET_S=60
- PAUSE_BUDGET_S=90
- 连续执行 3 轮
- 每轮 10 个并发
- 8 个矩阵组合；9、0 重复覆盖前两个带内存 Agent CBS 组合
- Pause 耗时：从触发 POST /pause 到轮询状态为 paused
- Resume 耗时：从首次 POST /connect 到 connect 成功
- Resume 后使用 connect 返回的 token 校验系统盘和 COS marker
1.2 暂停恢复 Serial 基准
- 8 个组合逐个顺序执行
- 每个组合执行 3 轮
- 流程：创建 → marker → pause 并轮询完成 → connect 恢复 → marker 校验 → 删除
1.3 Snapshot / Fork 矩阵
Snapshot 和 Fork 只测试 Agent CBS 系统盘，不包含 mem / non-mem 维度：
- 系统盘：Agent CBS
- 外挂存储：COS / 无 COS
- 每种模式执行 3 轮
- 每个 combo 每轮创建 1 个 source
- Snapshot：每个 snapshot 恢复 5 个实例
- Fork：每个 source fork 5 个实例
- Serial：5 个目标实例顺序创建
- Barrier：两个 combo 同时运行，每个 combo 同时创建 5 个目标实例，总并发 10
---
2. 暂停恢复 Barrier 矩阵
2.1 测试结果
30/30 全部通过。 表内耗时为 3 轮样本中位数；前两个组合因 9/10 重复覆盖，各有 6 个样本，其余组合各 3 个样本。

！创建沙箱的时间数据受健康探测周期设置影响，具体参考第 8 节附录
|#|组合|暂停模式|系统盘|外挂存储|创建|暂停完成|恢复完成|结果|
|-|-|-|-|-|-|-|-|-|
|1|mem+agentcbs-sysdisk+cosfs|带内存|Agent CBS|COS|6.5 s|3.4 s|568 ms|6/6|
|2|mem+agentcbs-sysdisk+no-cosfs|带内存|Agent CBS|无外挂|6.3 s|3.4 s|579 ms|6/6|
|3|mem+default-sysdisk+cosfs|带内存|默认系统盘|COS|6.3 s|3.4 s|1.1 s|3/3|
|4|mem+default-sysdisk+no-cosfs|带内存|默认系统盘|无外挂|6.2 s|4.4 s|1.6 s|3/3|
|5|non-mem+agentcbs-sysdisk+cosfs|不带内存|Agent CBS|COS|6.5 s|487 ms|6.4 s|3/3|
|6|non-mem+agentcbs-sysdisk+no-cosfs|不带内存|Agent CBS|无外挂|6.3 s|492 ms|6.4 s|3/3|
|7|non-mem+default-sysdisk+cosfs|不带内存|默认系统盘|COS|6.3 s|641 ms|6.7 s|3/3|
|8|non-mem+default-sysdisk+no-cosfs|不带内存|默认系统盘|无外挂|6.1 s|612 ms|6.3 s|3/3|

2.2 与广州报告对比
|指标|广州 2C4G|上海 1C1G|
|-|-|-|
|创建|9.4–15.5 s|6.1–6.5 s|
|带内存暂停|4.4–4.5 s|3.4–4.4 s|
|带内存 + Agent CBS 恢复|455–517 ms|568–579 ms|
|带内存 + 默认系统盘恢复|2.0 s|1.1–1.6 s|
|不带内存暂停|409–576 ms|487–641 ms|
|不带内存恢复|9.1–9.3 s|6.3–6.7 s|
|通过率|10/10|30/30|


上海结果与广州报告的性能特征一致：带内存暂停较慢但恢复快，不带内存暂停快但恢复慢。
---
3. 暂停恢复 Serial 矩阵
24/24 全部通过。 表内耗时为每个组合 3 轮中位数。

|#|组合|暂停模式|系统盘|外挂存储|创建|暂停完成|恢复完成|结果|
|-|-|-|-|-|-|-|-|-|
|1|mem+agentcbs-sysdisk+cosfs|带内存|Agent CBS|COS|6.5 s|3.3 s|558 ms|3/3|
|2|mem+agentcbs-sysdisk+no-cosfs|带内存|Agent CBS|无外挂|6.3 s|2.4 s|532 ms|3/3|
|3|mem+default-sysdisk+cosfs|带内存|默认系统盘|COS|6.3 s|3.4 s|1.3 s|3/3|
|4|mem+default-sysdisk+no-cosfs|带内存|默认系统盘|无外挂|6.1 s|3.3 s|1.5 s|3/3|
|5|non-mem+agentcbs-sysdisk+cosfs|不带内存|Agent CBS|COS|6.6 s|420 ms|6.4 s|3/3|
|6|non-mem+agentcbs-sysdisk+no-cosfs|不带内存|Agent CBS|无外挂|6.3 s|388 ms|6.4 s|3/3|
|7|non-mem+default-sysdisk+cosfs|不带内存|默认系统盘|COS|6.2 s|346 ms|6.3 s|3/3|
|8|non-mem+default-sysdisk+no-cosfs|不带内存|默认系统盘|无外挂|6.1 s|485 ms|6.3 s|3/3|


Serial 与 Barrier 的差异较小，说明 10 并发暂停恢复未出现明显资源争抢。
---
4. Snapshot 矩阵
Snapshot 不保存内存态，因此没有 mem / non-mem 维度。
4.1 Serial：每个 snapshot 顺序恢复 5 个实例
|组合|Source 创建|Snapshot 创建|单实例恢复|5 实例批次墙钟|结果|
|-|-|-|-|-|-|
|agentcbs-sysdisk+cosfs|6.5 s|0.3 s|6.4 s|34.0 s|15/15|
|agentcbs-sysdisk+no-cosfs|6.3 s|0.2 s|6.2 s|32.7 s|15/15|

4.2 Barrier：两个 combo 同时运行，每个 snapshot 同时恢复 5 个实例
总恢复并发为 10。

|组合|Source 创建|Snapshot 创建|单实例恢复|5 实例批次墙钟|结果|
|-|-|-|-|-|-|
|agentcbs-sysdisk+cosfs|6.5 s|0.2 s|6.4 s|6.8 s|15/15|
|agentcbs-sysdisk+no-cosfs|6.3 s|0.2 s|6.3 s|6.7 s|15/15|


Snapshot 共执行 12 个批次、60 个恢复实例，60/60 全部通过。10 路并发恢复时，单实例耗时基本不变，批次墙钟由约 33 秒降至约 6.8 秒 （Snapshot 可并发 Restore）。
4.3 Snapshot 并发
同一 source 能否并发创建 5 个 Snapshot
已额外对同一 source 同时提交 5 个 POST /sandboxes/{source-id}/snapshots。结果为 1 个成功、4 个 HTTP 409：

|请求|HTTP|耗时|RequestId|
|-|-|-|-|
|1|409|73.9 ms|89672de6-bab2-4cc3-8bc6-9e5cb8298866|
|2|409|79.2 ms|f9d522ee-c2f3-4e5f-8e54-7cd7fd8f3169|
|3|201|281.6 ms|成功响应未返回 RequestId|
|4|409|67.8 ms|85115b52-f4db-4967-860f-d0385c3ccec7|
|5|409|75.6 ms|2cd7302b-0b3f-4f1c-8733-209f03398b4b|


409 响应同样为：
[FailedOperation.PauseInProgress]
Pause, Resume or Fork operation already in progress for instance <source-id>
因此，同一个 source 上的 Snapshot 创建也受 Pause / Resume / Fork 生命周期操作互斥约束。报告中的 5 个 Snapshot 必须顺序创建；单个 Snapshot 约 219–222 ms，顺序创建 5 个总计约 1.1 秒，代价较低。

另外，4.2 已验证单个 Snapshot 同时 Restore 5 个实例也能 30/30 通过。因此实现大量实例派生时不需要预先创建 5 个 Snapshot：一个 Snapshot 可被多个并发 Restore 请求复用；创建多个 Snapshot 更适用于需要多个独立版本点的场景。
---
5. Fork 矩阵
Fork 不保存内存态，因此没有 mem / non-mem 维度。Playbook 中的用法是：把运行中 source 的 sandbox_id 作为 templateID 创建一个新沙箱。source 在 Fork 后仍保持运行，因此可以重复执行该调用，从同一个 source 依次生成多个相互独立的 Fork 实例。
forked_1 = create_from_ref(source.sandbox_id)
forked_2 = create_from_ref(source.sandbox_id)
forked_3 = create_from_ref(source.sandbox_id)
forked_4 = create_from_ref(source.sandbox_id)
forked_5 = create_from_ref(source.sandbox_id)
5.1 同一 source 顺序 Fork 出 5 个实例

这不是正常的“Fork 出 5 个实例”用法（正常用法参考 4.2，快速从 Snapshot 创建）
下表的“顺序 5 Fork 总墙钟”是从发起第 1 个 Fork 到第 5 个 Fork 创建和校验完成的总时间；不是 5 个 Fork 动作并发提交。

|组合|Source 创建|单实例 Fork|同源顺序 5 Fork 总墙钟|数据/隔离校验|结果|
|-|-|-|-|-|-|
|agentcbs-sysdisk+cosfs|6.4 s|6.4 s|33.9 s|通过|15/15|
|agentcbs-sysdisk+no-cosfs|6.3 s|6.4 s|33.7 s|通过|15/15|


结果说明同一个 source 可以 Fork 出多个实例。本次每个 source 顺序生成 5 个 Fork；两种组合 × 3 轮，共验证 30 个 Fork 实例，全部通过。
5.2 额外边界测试：同一 source 同时提交 5 个 Fork 请求
同样，这也不是正常的“Fork 出 5 个实例”用法（正常用法参考 4.2，快速从 Snapshot 创建），而是额外验证同源 Fork 操作能否并行。两个 combo 同时运行，理论请求并发为 10。

|组合|Source 创建|成功 Fork 耗时|同源 5 路并发尝试墙钟|结果|
|-|-|-|-|-|
|agentcbs-sysdisk+cosfs|6.2 s|6.5 s|7.0 s|3/15|
|agentcbs-sysdisk+no-cosfs|6.1 s|6.4 s|6.8 s|3/15|


每个 source 每轮只有 1 个 Fork 成功，其余 4 个请求立即返回：
HTTP 409
[FailedOperation.PauseInProgress]
Pause, Resume or Fork operation already in progress for instance <source-id>
一次独立复测的 source 为 smn47xxb5ctaq4uxzu4tofpcpwvrrdw2elmx3nxp。5 路并发请求中 1 个返回 201、4 个返回 409；4 个失败请求的 RequestId 分别是：
- 6369ab7c-96d2-4480-bd43-197572d6ee3f
- 6c81c2f7-241c-4938-b29e-e52e7c2db5e8
- 19314b63-42cc-43d1-9a91-a34eb103098b
- 4806db19-b360-4870-993b-fe0e6576bdce
成功请求返回 201 和新 sandboxID，但响应头和响应体均未返回 RequestId。

同一 source 上 Pause / Resume / Fork 操作互斥。因此：
- 不同 source 可以并发 Fork；
- 同一 source 一次只能进行 1 个 Fork；
- 若需从同一 source 生成 5 个 Fork，应顺序执行，或对 409 做等待重试；
- 顺序模式已经验证 30/30 全部成功。
---
6. 可审计测试计数
|测试|模式|组合|轮数|每组合每轮实例/请求|结果|
|-|-|-|-|-|-|
|暂停恢复|Barrier|8|3|1|30/30|
|暂停恢复|Serial|8|3|1|24/24|
|Snapshot restore|Serial|2|3|5|30/30|
|Snapshot restore|Barrier：单 Snapshot 多实例|2|3|每个 Snapshot 同时 Restore 5 个，总并发 10|30/30|
|Snapshot restore|Barrier：多 Snapshot 多实例|2|3|每个 source 建 5 个 Snapshot，各 Restore 1 个，总并发 10|30/30|
|Fork|目标场景：同源顺序执行|2|3|每个 source 顺序 Fork 5 个|30/30|
|Fork|额外边界：同源并发尝试|2|3|每个 source 同时提交 5 个请求|6/30|

---
7. 结论
1. 暂停恢复对齐广州脚本，上海 10 × 3 轮 30/30 通过，性能特征一致。
2. 暂停恢复 Serial 基线 24/24 通过，与 Barrier 数据接近。
3. Snapshot 创建约 0.2–0.3 秒；单实例恢复约 6.2–6.4 秒。单 Snapshot 同时恢复 5 个和 5 Snapshot 同时各恢复 1 个均 30/30 通过，可用于大量实例派生。
4. 一个 Snapshot 即可并发 Restore 多个实例；除非需要多个独立版本点，否则不必为每个目标实例创建独立 Snapshot。
5. Fork 单实例约 6.4 秒；同一 source 顺序 Fork 5 个 30/30 通过。
6. 同一 source 不支持 5 路同时 Fork：每轮 1 个成功、4 个返回 409 操作互斥。并发派生优先使用 Snapshot Restore。
8. 附录
在 50 并发下，依次设置 ProbePeriodMs 为 500/1000/2000/5000/10000 ms，各跑 2 轮（每档 100 个实例，共 500 个实例，500/500 全部成功）：

|探测周期|样本|Create avg|Create 中位数|Create P90|Create max|第 1 轮批次墙钟|第 2 轮批次墙钟|
|-|-|-|-|-|-|-|-|
|500 ms|100|1.71 s|1.67 s|1.88 s|1.96 s|2.36 s|2.22 s|
|1000 ms|100|1.80 s|1.68 s|2.16 s|2.45 s|2.64 s|2.82 s|
|2000 ms|100|2.03 s|1.67 s|3.23 s|3.44 s|4.39 s|4.43 s|
|5000 ms|100|5.54 s|6.12 s|6.33 s|6.36 s|6.76 s|6.71 s|
|10000 ms|100|8.64 s|6.40 s|11.32 s|11.40 s|11.63 s|11.77 s|


分析：
- 500/1000/2000 ms 档创建中位数都是约 1.67 s，几乎没有差别；差异主要体现在 P90/最大值（探测等待的最坏情况）。
- 5000 ms 档跳到约 6.12 s，与早期默认配置（探测 5s）的 6.1–6.3 s 完全一致。
- 10000 ms 档中位数约 6.40 s 但 P90/max 到 11.3–11.4 s，最坏情况等于一个完整探测周期。
- 批次墙钟与探测周期近似线性：约等于创建中位数 + 一个探测周期（50 并发下并行度良好，未出现排队放大）。
