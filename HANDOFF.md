# 分层时变 Cox 增量交接说明

本说明配合 `COX.md`，记录 V2（分层 Efron Cox）在 V1 归档之上的落点、不变量与核验入口。

## 模块落点

- 接纳层 `reliability/records/intervals.py`：`Interval` 增加可选 `x`（1 或 2 个
  非布尔整数/`Fraction` 分量，规范为 `Fraction` 元组）。无 `x` 的区间保持 V1 语义，
  不补零、不借用 `load`；仅改 `x` 的同 ID 请求构成内容冲突。
- 编码层 `reliability/archive/codec.py`：新增有限 `float` 标签，Cox 正文的浮点数值与
  `Fraction/int/bool/None` 严格区分；旧编码读取不变。
- 模式层 `reliability/archive/schema.py`：新增 `risk_plans`、`cox_report_bodies`。
  打开本树 V1 建立的归档时，在同一 `schema_version=1` 下幂等补齐新表/索引，
  不重置任何历史；新库一次建齐。
- 计划层 `reliability/cohorts/risk.py` + `snapshots.py`：`compile_risk` 执行
  80 设备 / 160 区间 / 4 分层 / 统一维数校验，按精确 `(start,stop]` 编译风险成员与
  同刻 Efron 事件，整笔事务保存；`load_risk` 只读解码，返回独立副本。
- 数值层 `reliability/analysis/cox_engine.py`：浮点 Newton 求解未加权对数偏似然，
  解析负 Hessian（信息矩阵），按批次权重的混合导数计算聚类得分，
  `cov = H^-1 (Σ_g U_g U_g^T) H^-1`（无自由度修正）。
- 服务/正文层 `reliability/analysis/cox.py`、`reliability/reports/cox_content.py`：
  `fit_cox` 只消费已保存计划；无故障发布 `no_events` 且不产生系数。报告头仍写入
  既有 `reports` 表，正文入 `cox_report_bodies`，因此 V1 的 `AFTER INSERT ON reports`
  触发器失败方式对新类型同样生效并整体回滚。
- 读取/比较层 `reliability/reports/read.py`、`compare.py`：同一 `read` 按 basis 分派；
  Cox 报告不参与描述性 `compare`，任一侧为 Cox 即抛 `ValueError`。

## 关键不变量

1. 计划固定：风险成员、故障时刻、批次归属、来源修订与成员在 `compile_risk` 时冻结；
   后续更正、对象修改、关闭重开都不改变旧计划或旧报告，读取不重新拟合。
2. 边界精确：层内时刻 t 的风险成员恰为 `start < t <= stop` 的区间设备，使用该段 `x`；
   同刻多故障保留为单个 Efron 事件，间隙与其他分层不进入分母。
3. 拆分不变：把无故障区间在内部时刻拆成相邻且 `x` 相同的两段，事件投影与全部数值不变。
4. 批次聚类：先在每个事件内按批次累计混合导数，再跨事件、跨层合并同一批次得分，
   最后才形成协方差；无事件贡献的批次保留在计划成员中（无故障报告不发布得分）。
5. 事务原子性：计划提交与报告提交各自是完整事务，不存在可读的半成品；发布失败回滚后
   可对同一 `plan_id` 重试，生成新报告而旧报告不变。
6. 数值口径：契约保证的输入下，所有返回值为有限 float，相对 60 位 Decimal 独立参照的
   绝对误差远小于 1e-7（满规模压力测试约 1e-14）。

## 独立核账

`audit/cox_audit.py` 不导入任何 `reliability` 代码：它从归档成员区间重新编译风险集，
用 `decimal.Decimal`（60 位）独立实现 Newton 求解、Efron 似然、批次混合导数与矩阵求逆。
`tests/test_cox_audit.py` 把生产结果与该参照逐项比对，并覆盖非零系数、并列故障、
二维信息、跨层共享批次、进入/退出端点、区间拆分、满规模压力与无故障状态。

## 核验入口（沿用 .pointwise-runtime.json）

- `python3.11 -B run.py verify`：全部 54 个 V1+V2 测试，任一失败非零退出。
- `python3.11 -B run.py demo --db demo.sqlite3`：原 V1 业务演示，保持不变。
- `python3.11 -B run.py cox-demo --db cox_demo.sqlite3`：跨层批次拟合、拆分不变、
  更正后新旧计划并存，以及关闭重开读取旧报告/旧计划并重试。
