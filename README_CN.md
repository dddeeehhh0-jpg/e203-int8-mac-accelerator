# 基于 E203 的 INT8 MAC 加速器（clean-room 演示工程）

[![regress](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/workflows/ci.yml/badge.svg)](https://github.com/dddeeehhh0-jpg/e203-int8-mac-accelerator/actions/workflows/ci.yml)

*仓库为 Private 时，badge 仅登录用户可见。*

独立重写的小型 INT8 MAC 数据通路：8 路并行有符号乘法、32 位累加、`r32`
再量化（四舍五入 + 单次输出饱和），另有一个 NICE 风格指令适配器，以及一个
能跑通 12 层前馈链的最小宿主 FSM。每条数据通路规则都配有位精确 Python
参考模型、可复现向量和自检 testbench。

> **本仓库不是比赛工程**：不含 E203 核、官方 NICE RTL、PDK、网表、数据集、
> 权重、比赛源码与截图。比赛经历只在 `docs/case_study.md` 里写方法与结论。

英文主入口见 [README.md](README.md)。

---

## 状态表（先看这个）

| 组件 | 状态 | 证据 |
|---|---|---|
| 位精确 Python 模型 | 已完成，8 项穷举自检 | `model/int8_ref.py` |
| 确定性向量集 | 已完成，8 个文件含 sha256 | `vectors/gen/manifest.csv` |
| 独立黄金值复核 | 已完成（8.8 万+ 点） | `check_results.py --verify-vectors` |
| 8 个 RTL 模块 | 已写，语法解析 14/14 | `results/parse_report.txt` |
| 结构 lint | 已完成，0 error | `results/lint_report.txt` |
| 6 个自检 testbench | **CI 真实仿真 6/6 全 PASS**（Icarus Verilog 12.0） | `results/ci_evidence.md` |
| Linux CI 回归 | **全绿** — run `43226906536`，`--strict`，6 个 TB 与 scoreboard 全 PASS | `results/ci_evidence.md`、`.github/workflows/ci.yml` |
| 逻辑级综合 | 仅脚本，无 PDK、无 PPA 数字 | `syn/` |

**如实说明**：作者本机的 `iverilog` 安装包被 Windows 安全策略拦截，六个
Verilog testbench **未在本机执行**（本机快照 `results/regression_summary.md`
里写的是 `SKIPPED`）。但它们已在 GitHub Actions（`ubuntu-latest`，
Icarus Verilog 12.0）真实跑过：六个 TB 全 PASS，独立 Python scoreboard 对
六份 RTL dump 均为 0 mismatch。首个 run `43226072305` 曾因 scoreboard 未遵守
握手协议而失败，修复在核对脚本、不在 RTL；完整日志、run ID 与 commit hash
见 `results/ci_evidence.md`。**CI 结果才是 RTL 的权威结论，本机快照不是。**

---

## 定点契约

```
acc   = sum_i(x_i * w_i) + bias          // 32 位有符号回绕
q     = acc * r32 + 2^15                // 49 位有符号
y_pre = q >>> 16                        // 算术右移，不是逻辑右移
y     = clip(y_pre, -128, 127)          // 只在输出级饱和一次
```

| 信号 | 位宽 | 说明 |
|---|---|---|
| `x[i]`, `w[i]` | 8 | 有符号 INT8 |
| 单 lane 乘积 | 16 | `(-128)*(-128)=16384` 仍装得下 |
| `acc` | 32 | 含 bias，中途不截断 |
| `r32` | 16 | 运行时比例因子，非 2 的幂也可表达 |
| `q` | 49 | `2^31 * 2^16 + 2^15 < 2^48` |
| `y` | 8 | 有符号 INT8，`sat_flag` 报告饱和 |

`+2^15` 是四舍五入而非截断：截断会给每层引入系统性负偏置。
`r32` 用真乘法而不是移位，才能连续逼近任意层比例。

![架构](docs/images/fig1_architecture.png)

![数据通路与位宽](docs/images/fig2_dataflow.png)

![验证流程](docs/images/fig3_verification.png)

---

## 验证

| Testbench | 覆盖 | 点数 |
|---|---|---|
| `tb_mac_pe` | 256x256 全组合 | 65,536 |
| `tb_mac_array` | 5,000 随机 + 4 组极值 | 5,004 |
| `tb_requant` | r32 全扫 x 17 个 acc 边界 | 17,459 |
| `tb_top_stream` | 24 拍：配置、背靠背、反压、流中复位 | 24 |
| `tb_nice_adapter` | 1 组合法 + 5 类非法序列 | 13 |
| `tb_soc_stub` | 12 层端到端 + 写回内存复核 | 12 |

**不声称覆盖率数字**（没有商用覆盖率工具就不编）。每个数字都指向
`results/` 或 `vectors/gen/manifest.csv` 里的具体文件。

---

## 快速开始

```bash
# 作者本机实际跑过（Windows / Python 3.13）
python3 model/int8_ref.py
python3 model/gen_vectors.py
python3 -m pip install pyverilog                 # 可选：真实语法解析
python3 model/check_results.py --verify-vectors --selftest
python3 model/rtl_lint.py
python3 model/verilog_parse_check.py
python3 run_regress.py
```

Linux / CI（装有 iverilog，run `43226906536` 已全绿通过）：

```bash
sudo apt-get install -y iverilog
python3 run_regress.py --strict
make regress
```

`--strict` 会把"仿真被跳过"判为失败，所以 CI 绿灯才代表六个 TB 真跑过。
六个 TB 的实际输出与逐点比对结果见 `results/ci_evidence.md`。

---

## 明确不包含

1. E203 核与官方 NICE 实现：`nice_adapter.v` 是自定义 funct7 编码的简化版。
2. PDK、SRAM 宏、网表、门级回放：`sram_beh.v` 只是行为模型。
3. 数据集、训练权重、音频：所有激励由 `SEED = 20261112` 确定性生成。
4. 比赛源码、截图、服务器路径：见 `docs/PUBLICATION_AUDIT.md` 的三色清单。

---

## 文档索引

| 文件 | 内容 |
|---|---|
| `docs/architecture.md` | 模块划分、接口表、模式编码 |
| `docs/fixed_point_design.md` | 位宽推导、舍入与饱和证明 |
| `docs/verification.md` | 六个 TB、向量机制、证据链 |
| `docs/synthesis_analysis.md` | 逻辑级综合能说明什么、不能说明什么 |
| `docs/project_limitations.md` | 已知限制与未做事项 |
| `docs/case_study.md` | 比赛团队项目：只写方法与结论 |
| `docs/resume_project.md` | 简历 3 行版与面试八问 |
| `docs/PUBLICATION_AUDIT.md` | 逐文件合规清单 |

---

## 许可证

MIT，见 [LICENSE](LICENSE)。发布前请把版权人改成自己的名字。
