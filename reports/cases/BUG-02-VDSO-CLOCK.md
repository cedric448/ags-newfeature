# BUG-02：AGS 沙箱内 `clock_gettime(CLOCK_MONOTONIC)` 回退系统调用，vDSO 快路径失效

| 项 | 值 |
|---|---|
| 缺陷编号 | **BUG-02** |
| 严重度 | **高**（性能类，影响基准评测结果可比性） |
| 状态 | 待修复 |
| 发现日期 | 2026-11-07 |
| 复现地域 | `ap-beijing`（本次）；`ap-singapore`（用户原始报告） |
| 影响版本 | 内核 `6.6.69-cube.pvm.guest.005.x-g039db8913c80` |
| 影响范围 | **全部** Tool 类型（custom / code-interpreter）、全部网络模式（SANDBOX / VPC） |
| 提出方 | 用户侧基准评测（naive-bench） |

---

## 1. 问题摘要

AGS 沙箱内调用 `clock_gettime(CLOCK_MONOTONIC)` **不会走 vDSO 用户态快路径**，
每次调用都陷入内核执行真实系统调用，单次开销约为正常环境的 **9–10 倍**。

由于高精度计时是绝大多数基准程序（含 KV 缓存、请求限流、延迟埋点）的热路径，
该缺陷直接导致 **AGS 上的性能评测结果与 Docker/物理机不可比**。

| 指标 | AGS 沙箱 | 正常 Linux（含普通 KVM 虚机） | 劣化 |
|---|---|---|---|
| `clock_gettime(MONOTONIC)` | **240–297 ns** | 26–29 ns | **8–11 倍** |
| `clock_gettime(MONOTONIC_COARSE)` | 3.9 ns | 5.8 ns | 正常 ✅ |
| 真系统调用 `getppid()` | 224 ns | 59 ns | 3.8 倍（基线） |
| **单次调用是否陷入内核** | **是** | 否 | — |

### 业务影响（用户实测）

| 场景 | 吞吐 |
|---|---|
| KV 参考解 @ AGS | 69–73 万 req/s |
| KV 参考解 @ Docker | 184–186 万 req/s |
| 同上，仅诊断进程改用粗粒度时钟 | 69 万 → **140 万 req/s（2.03×）** |

> 该实验仅用于定位，正式评分产物未修改。

---

## 2. 环境

| 项 | 值 |
|---|---|
| 内核 | `6.6.69-cube.pvm.guest.005.x-g039db8913c80` |
| CPU | AMD EPYC 9754 / 9K65 |
| 虚拟化 | PVM（存在 `kvm_pvm_guest` 标记） |
| 当前 clocksource | `kvm-clock` |
| 可用 clocksource | `kvm-clock acpi_pm` |
| glibc | Debian GLIBC 2.41-12+deb13u2 |
| `[vdso]` 映射 | 存在（`7fffe55c6000-7fffe55c8000 r-xp`） |
| 对照主机 | `6.6.110-42.4.tl4.x86_64`，同为 KVM 虚机 |

---

## 3. 复现步骤

### 3.1 最小复现程序

```c
#define _GNU_SOURCE
#include <stdio.h>
#include <time.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(void) {
    struct timespec a, b, ts;
    long n = 20000;

    /* ① glibc 调用：正常应命中 vDSO */
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (long i = 0; i < n; i++) clock_gettime(CLOCK_MONOTONIC, &ts);
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("via_glibc   = %.1f ns\n",
           ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / n);

    /* ② 强制系统调用作为基线 */
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (long i = 0; i < n; i++) syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &ts);
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("via_syscall = %.1f ns\n",
           ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / n);
    return 0;
}
```

编译：`gcc -O2 -o v v.c`

### 3.2 关键判据

**若 `via_glibc ≈ via_syscall`，即证明 vDSO 快路径未生效。**

实测：

```
# AGS 沙箱
via_glibc   = 240.0 ns
via_syscall = 240.2 ns      ← 两者几乎相等，未走 vDSO

# 正常主机
clock_gettime  = 29.4 ns    ← vDSO 快路径生效
syscall(getppid) = 58.7 ns
```
---

## 4. 影响范围验证

### 4.1 跨 Tool 类型 / 镜像 / 网络模式

在 `ap-beijing` 对 5 个不同 Tool 逐一实测（同一台宿主机内核）：

| Tool 类型 | Tool 名称 | 网络模式 | 内核 | `clock_gettime` |
|---|---|---|---|---|
| custom | `agstest-clockprobe-*` | SANDBOX | `6.6.69-cube.pvm.guest` | 290.6 ns |
| custom | `custom-fredtest-2` | SANDBOX | 同上 | 286.4 ns |
| custom | `custom-fredtest-2-copy` | **VPC** | 同上 | 289.8 ns |
| custom | `evocodebench-coding` | SANDBOX | 同上 | 265.2 ns |
| **code-interpreter** | `test-1782135449` | — | 同上 | 296.9 ns |

**结论：与 Tool 类型、镜像、网络模式均无关，全部复现。**

### 4.2 与 Tool 类型无关（补充说明）

初测时曾观察到不同 Tool 的 dmesg 内容存在差异，一度怀疑与镜像有关。
经 4.1 的 5 个 Tool 横向对比确认：**性能表现完全一致，dmesg 差异仅为采集时机不同**。

后续精确对比发现，kvm-clock 的初始化日志在**全部** AGS 沙箱中均缺失，
这是 PVM 环境的共性特征，见 5.3。

### 4.3 已排除的方向（用户侧与本次共同确认）

| 排查项 | 结论 |
|---|---|
| 完整特权模式 | 仍复现 |
| 关闭 seccomp | 仍复现 |
| 新建克隆 Tool | 仍复现 |
| 前轮 9 个新沙箱 | 全部复现 |
| 本轮 8 个有效特权/克隆样本 | 全部复现 |
| 是否有禁用计时快路径的启动参数 | 未发现 |
| 相关内核配置是否开启 | 已开启 |
| 测量时是否有 Task/DinD/Agent/Verifier 干扰 | **无**（已排除） |

---

## 5. 根因分析与定位建议

### 5.1 现象拆分

同一实例内三类时钟调用对比（AGS 沙箱）：

| 调用 | 耗时 | 路径 |
|---|---|---|
| `clock_gettime(CLOCK_MONOTONIC_COARSE)` | **3.9 ns** | ✅ vDSO 生效 |
| `clock_gettime(CLOCK_MONOTONIC)` | 240–262 ns | ❌ 回退 syscall |
| `syscall(SYS_getppid)` | 224 ns | 真系统调用基线 |

**`COARSE` 正常、`MONOTONIC` 异常**，说明 vDSO 映射本身可用，
是 **`CLOCK_MONOTONIC` 分支的判定条件不满足**。

### 5.2 机制推断

Linux vDSO 的 `__vdso_clock_gettime` 在 `CLOCK_MONOTONIC` 分支需要：

1. 当前 clocksource 支持 vDSO（kvm-clock 需 `vdso_clock_mode != VDSO_CLOCKMODE_NONE`）
2. 能安全读取 pvclock 结构（依赖 TSC 频率稳定性标识）

`CLOCK_MONOTONIC_COARSE` 走另一条分支（读 timekeeper 的粗粒度缓存），
不依赖 pvclock 序列读取，故不受影响。

### 5.3 根因证据：kvm-clock 初始化日志完全缺失

**决定性证据**来自 dmesg 精确对比：

| dmesg 输出 | 正常主机（KVM 虚机） | AGS 沙箱 |
|---|---|---|
| `Hypervisor detected: KVM` | ✅ | ❌ **缺失** |
| **`kvm-clock: Using msrs 4b564d01 and 4b564d00`** | ✅ | ❌ **缺失** |
| **`kvm-clock: using sched offset of ... cycles`** | ✅ | ❌ **缺失** |
| `clocksource: kvm-clock: mask: 0xffff..., max_cycles...` | ✅ | ❌ **缺失** |
| `kvm-guest: PV spinlocks enabled` | ✅ | ❌ 缺失 |
| `kvm-guest: setup PV IPIs` | ✅ | ❌ 缺失 |
| `clocksource: Switched to clocksource kvm-clock` | ✅ | ✅ **仅此一条** |

AGS 沙箱**只有最后一行的「切换」，完全没有 kvm-clock 的注册与初始化过程**。

正常主机的完整链路是：

```
Hypervisor detected: KVM
  → kvm-clock: Using msrs 4b564d01 / 4b564d00     ← 发现 pvclock MSR
  → kvm-clock: using sched offset ...              ← 初始化 sched 偏移
  → clocksource: kvm-clock: mask/max_cycles        ← 注册 clocksource，设置 mask
  → Switched to clocksource kvm-clock              ← 切换
```

AGS 沙箱跳过了前 3 步，直接执行了 switch。**`clocksource->mask` 未正确设置、pvclock 页未建立**，
这正是 `vdso_clocksource_ok()` 判定失败的直接原因。

### 5.3.1 已排除的假设：TSC 能力标记（修正前判断）

初期推测 CPUID 剥离了 TSC 稳定性位，经精确实测**排除**：

| CPU flag | 正常主机 | AGS 沙箱 |
|---|---|---|
| `tsc` | ✅ | ✅ |
| `rdtscp` | ✅ | ✅ |
| `tsc_known_freq` | ✅ | ✅ |
| `constant_tsc` | ❌ 无 | ❌ 无（**两边一致**） |
| `nonstop_tsc` | ❌ 无 | ❌ 无（**两边一致**） |
| `arat` | ✅ | ✅ |
| `hypervisor` / `vmmcall` | ✅ | ✅ |
| **`kvm_pvm_guest`** | ❌ | ✅ **唯一差异** |

**关键点**：正常主机同样没有 `constant_tsc`，但 vDSO 工作正常（29 ns）。
因此「标记缺失」不是根因，**唯一的环境差异是 `kvm_pvm_guest`（PVM 模式）**。

### 5.3.2 修正后的根因链路

```
PVM 模式（kvm_pvm_guest）
   ↓
宿主的 KVM pvclock MSR（0x4b564d01 / 0x4b564d00）在 PVM 下不可用或未暴露
   ↓
guest 内核 kvmclock_init() 提前返回，跳过 pvclock 页映射与 clocksource 注册
   ↓
clocksource->mask 未设置，vdso_clock_mode = VDSO_CLOCKMODE_NONE
   ↓
__vdso_clock_gettime 对 CLOCK_MONOTONIC 判定失败 → fallback syscall
```

这解释了为什么：
- **与 Tool 类型/镜像/网络模式全部无关**（问题在 guest 内核启动阶段）
- **COARSE 正常**（不依赖 pvclock）
- **关闭 seccomp / 完全特权无效**（不是运行时权限问题）

### 5.4 建议排查的具体代码位置

按**修正后**的根因（kvm-clock 初始化未执行），建议优先排查：

| 优先级 | 位置 | 检查点 |
|---|---|---|
| **P0** | `arch/x86/kernel/kvmclock.c` — `kvmclock_init()` | 函数是否被调用、是否在 PVM 下提前 return |
| **P0** | `kvmclock_init_mem()` | pvclock 页（`hvclock_mem`）是否成功分配并映射到 guest |
| **P0** | PVM 的 MSR 访问路径 | pvclock MSR `0x4b564d01` / `0x4b564d00` 在 PVM 下是否可读 |
| **P1** | `kvmclock_setup_percpu()` | 每 CPU 的 `hvclock` 指针是否建立 |
| **P1** | `arch/x86/entry/vdso/vclock_gettime.c` | `vdso_clocksource_ok()` / `vdso_clock_mode` 实际值 |
| P2 | `pvclock_clocksource_read()` | 读取失败时内核是否静默降级 |

### 5.5 平台侧可快速验证的诊断命令

在可疑实例内执行，**只需第 ① 条即可判定**：

```bash
# ① 核心判据：kvm-clock 初始化是否执行
dmesg | grep -E 'kvm-clock|Hypervisor detected'
#   正常应输出 4 行（Hypervisor detected / Using msrs / sched offset / mask）
#   AGS 沙箱仅有 'Switched to clocksource kvm-clock' 一行

# ② 对照测量（本报告 3.1 的程序）
#   若 via_glibc ≈ via_syscall 即可确认回退

# ③ 确认 clocksource
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
```

**预期**：修复后 `via_glibc` 应降至 30 ns 量级，dmesg 应出现 `kvm-clock: Using msrs ...`。

---

## 6. 临时缓解方案

在平台修复前，业务侧可择一使用：

| 方案 | 做法 | 精度 | 风险 |
|---|---|---|---|
| **改用粗粒度时钟** | `CLOCK_MONOTONIC_COARSE` / `CLOCK_REALTIME_COARSE` | ~1 jiffy（4 ms） | 沙箱内实测 **3.9 ns，完全正常**；但精度不足，不适合微秒级延迟统计 |
| **降低计时频率** | 批量打点、按 N 次采样一次 | 视采样率 | 影响统计粒度 |
| **外置计时** | 业务逻辑内不做高精度计时，由外部采集 | — | 改造量大 |

> 用户侧已验证：仅诊断进程改用粗粒度时钟，吞吐从 69 万升至 140 万 req/s（2.03×）。
> 但 **正式评分产物未采用**，因为会影响精度。

---

## 7. 期望结果

| 检查项 | 期望 |
|---|---|
| `clock_gettime(CLOCK_MONOTONIC)` 单次耗时 | ≤ 50 ns（与常规 KVM 虚机持平） |
| `via_glibc` 与 `via_syscall` | 显著分离（不再相等） |
| `/proc/cpuinfo` | 出现 `constant_tsc`，建议同时具备 `nonstop_tsc` |
| KV 参考解吞吐 | 与 Docker 环境可比（差距 < 10%） |

---

## 8. 附件与复现脚本

| 文件 | 说明 |
|---|---|
| `scripts/bug02_clock_vdso.py` | 完整复现脚本：自动建实例、编译探针、采集各时钟开销并输出判定 |

复现命令：

```bash
python3 scripts/bug02_clock_vdso.py --tool custom-fredtest-2
python3 scripts/bug02_clock_vdso.py --all      # 遍历多个 Tool 类型
```

---

## 9. 时间线

| 日期 | 事件 |
|---|---|
| 2026-11-07 | 用户报告 ap-singapore 环境 KV 基准吞吐异常，定位到高精度计时回退 |
| 2026-11-07 | 本报告在 ap-beijing 独立复现，确认与 Tool 类型/镜像/网络模式无关 |
| 2026-11-07 | 通过 glibc vs syscall 对照实验确认 vDSO 未生效 |
| 2026-11-07 | 定位到 TSC 能力标记缺失（`constant_tsc` / `tsc_known_freq` 等） |
| — | 提交平台，待修复 |

---

## 10. 一句话总结

> **AGS 的 PVM guest 内核没有向 vDSO 暴露可用的 kvm-clock，
> 导致 `clock_gettime(CLOCK_MONOTONIC)` 每次陷入内核（240–297ns vs 正常 26–29ns），
> 基准吞吐因此损失约 2 倍。建议优先检查 PVM 模式下 TSC 稳定性 CPUID 位透传与 kvmclock 的 vDSO 初始化。**
