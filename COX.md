# 分层时变 Cox 分析增量契约

现有正常流程、原始 API 和全部原测试见 README.md。本文件与题面共同定义新增分析；当前树只实现 V1，以下新增入口尚未实现。cox_examples.py 只提供输入及预期数值，不提供编译器、求解器或导数实现。

## 共同结果与入口

记录员提交精确时变协变量；队列加工固定故障时刻的真实风险成员；分析执行使用该计划给出共同系数及批次聚类协方差。不能以平均负载、分层独立拟合或独立设备标准误代替。

保留现有导入和方法，新增公开调用如下：
- reliability.cohorts.snapshots.CohortService(archive).compile_risk(cohort_id) -> dict：编译、原子保存并返回固定计划的独立副本。
- 同一服务的 load_risk(plan_id) -> dict：只读回已保存计划，返回独立副本。
- reliability.analysis.cox.CoxService(archive).fit_cox(plan_id) -> int：消费已保存计划，计算并原子发布一个报告，返回报告 ID。再次调用允许发布新报告。
- 现有 reliability.reports.read.ReportReader(archive).read(report_id) 同时支持原描述性报告与新增 Cox 报告，不重新执行分析。
- 现有 ReportComparator.compare 保持描述性比较；任何一侧为 Cox 报告时抛 ValueError，不计算系数差值。

未知队列、计划、报告抛 KeyError。compile_risk 的输入不符合下列新增分析范围时抛 ValueError，不保存半份计划。存储异常原样传播；计划提交与报告提交分别为完整事务，不存在可读取的半份成果。具体持久表示及内部求导组织由实现决定。

## 区间输入与 V1 兼容

RecordService.apply 的设备结构不变。每段仍有 start、stop、load、failed，可额外有 x；不得接受其他未知字段。x 为长度 1 或 2 的 list/tuple，分量接受非布尔整数或 Fraction，规范值为 Fraction，顺序是系数坐标顺序。空向量、浮点数、布尔数或其他类型使整批 ValueError。x 缺省表示该段没有协变量，不隐式使用 load、不补零；这类记录仍完整支持 V1。load 继续只按 V1 规则计算描述性暴露，x 不参与该计算。

run.decode_submission 同样接纳可选 x 数组，数组中每个数使用原整数或[分子,非零分母]编码。x 必须随请求规范身份、历史区间、队列成员及摘要保存；仅更改 x 的同 ID 请求是冲突，等值分数及 list/tuple 不构成冲突。旧的缺省 x 请求、旧队列和旧报告继续可读，旧请求重放仍返回原回执；缺省 x 不能因规范化新增默认字段而改变旧请求身份。原全部设备时间线、整批拒绝、历史选择及复制隔离规则不变。支持扩充存储，但必须能打开本树 V1 建立的正常归档，不要求支持其他格式。

compile_risk 限最多 80 个选中设备、160 段、4 个分层；所有非空区间必须提供 x，且整个队列维数相同。空区间设备保留身份、批次和分层，不贡献风险成员或故障；全部设备都无区间时 p=0。其他情况 p 为公共向量长度。这些范围只约束新增分析，不限制原描述性接口。

## 固定、可检查的计划

compile_risk 和 load_risk 返回以下公开投影，内部可使用其他表示：
{
  "plan_id": 整数,
  "cohort_id": 原队列整数ID,
  "revision": 原知识修订,
  "p": 0、1或2,
  "members": 原队列的完整成员摘要列表（含规范后的可选x）,
  "events": [
    {
      "stratum": 分层,
      "time": Fraction故障时刻,
      "risk": [
        {"device_id": 设备, "batch_id": 批次, "x": Fraction列表}
      ],
      "deaths": [故障设备ID]
    }
  ]
}

members 按设备 ID 排序；events 按(stratum,time)排序，只列确有故障的层内时刻；risk 与 deaths 按设备 ID 排序。层内时刻 t 的风险成员恰为满足 start<t<=stop 的该层区间对应设备，使用这一段的 x；同一设备只出现一次。deaths 是在 t 的 stop 发生故障的设备集合，必须是 risk 的子集。同刻所有故障共同保留，不排列成若干单独事件。设备在 t 开始的下一段不能提前覆盖在 t 结束的上一段。间隙不提供风险成员，其他层不进入该分母。原队列修订、完整成员及设备到批次的归属随计划持久固定。

把一个不含故障的区间在内部时刻拆成相邻且 x 相同的两段，事件投影中的设备身份、批次和 x 必须相同；不要求完整 members 的原区间分段相同，也不要求新建对象 ID 相同。计划不可因后续更正、返回值修改或重开变化。fit_cox 必须消费此计划，不重读当前设备头或重新编译来源队列来替代计划。

## 目标、批次权重与报告

对每个层内事件，D 为 m 个故障成员，R 为风险成员，eta_i=x_i·beta。所有层共用一个 p 维 beta。未加权对数部分似然是各事件下式之和：
sum(i in D) eta_i - sum(l=0..m-1) log(sum(i in R) exp(eta_i) - (l/m)*sum(i in D) exp(eta_i))。

批次权重只为定义聚类得分，不是新的用户输入。给计划全部成员中的每个不同 batch_id 一个独立权重 w_g；同批设备及其所有区间、跨层记录共享这个身份。该事件的加权目标为：
sum(i in D) w_g(i)*eta_i
- ((sum(i in D) w_g(i))/m)
  * sum(l=0..m-1) log(sum(i in R) w_g(i)*exp(eta_i) - (l/m)*sum(i in D) w_g(i)*exp(eta_i))。
这里 w_g(i) 表示成员 i 所属批次的权重；m、R、D 始终固定，不随权重改变，不能把权重解释为复制或删除故障身份。

beta 为未加权总目标的极大点。H 为此处未加权负 Hessian；U_g 为总加权目标对 beta 和 w_g 的混合导数，在该 beta、全部 w=1 处计算。先跨事件、跨层合并每个批次的 U_g，再计算 covariance = H^-1 * (sum_g U_g U_g^T) * H^-1；不加自由度修正。批次没有事件贡献时其得分为零，仍保留该批次。报告 beta、log_likelihood、information、batch_scores、covariance 的每个数须是有限 float，相对于独立高精度参照绝对误差不超过 1e-7。

只要求处理含故障时存在唯一有限极大点且 H 正定的输入，不要求分离诊断或不可识别拟合。为使 float 的绝对误差要求有界，含故障的输入另保证：最优 beta 各分量绝对值不超过 8，最优 H 特征值在[0.001,1000]内，全部应返回的数值绝对值不超过 10000。这些是调用方保证，无需实现判定或违规诊断，不用数值保证充当新增性能要求。允许全量重算、逐事件扫描、成熟数值方法或精确/高精度内部计算，不规定优化算法。

新增报告 read 的字典包含：
report_id、format_version=1、basis="stratified-efron-batch-v1"、plan_id、cohort_id、revision、p、
status、beta、log_likelihood、information、batch_scores、covariance。
成功有事件时 status="ok"，beta 为 p 元列表，information 与 covariance 为 p×p 行列表，batch_scores 为按 batch_id 排序的列表，每项 {"batch_id":字符串,"score":p元列表}。
无任何故障（包括空队列）时仍发布固定报告，status="no_events"，beta、information、covariance 均为 None，log_likelihood=0.0，batch_scores=[]，不伪造系数。

报告保存绑定与完整数值正文，读取不拟合、不访问来源设备或队列，旧描述性报告结构和语义保持原样。新报告发布必须使用既有报告头 reports 的可观察发布边界，支持 tests/test_publish.py 相同的 AFTER INSERT ON reports 失败触发方式：失败不留新报告或半份正文、不损坏旧成果，移除触发器后可对原 plan_id 重试。新增类型的正文可采用适合的存储方式，但不能将 float 当 Fraction/int 混淆，不能破坏旧编码读取。

## 样例和交付核验

cox_examples.py 可直接打印样例，不调用目标实现。tied_case 是两个层各有两名并列故障、批次跨层共享的有限拟合样例。其精确期望为 beta=[0]、log_likelihood=-2*log(12)、H=[[47/72]]，批次 g 的得分为[25/72]、h 为[-25/72]，协方差为[[1250/2209]]。
vector_case 的期望为 beta=[0,0]、log_likelihood=-2*log(12)、H=diag(5/3,7/3)，批次 g 得分[7/6,-7/6]、h 得分[-7/6,7/6]，协方差[[49/50,-7/10],[-7/10,1/2]]。
boundary_case 只检验编译：t=2 时 risk 设备为 A、C，deaths 为 A，B 不在风险集；不将此样例用于有限拟合承诺。split_tied_case 把 tied_case 的一段在 t=1 拆开，事件成员和拟合数值应与 tied_case 一致。

交付各职责的联动实现及简短交接不变量说明。独立核账须覆盖公开公式下的非零系数、并列故障、两维信息、跨层共享批次、进入退出端点和区间拆分；核账不能只调用生产目标函数自证。保留全部原测试，验证 V1 接纳、描述性计算、历史队列和报告读取；新增验证贯穿接纳—冻结—编译—拟合—更正—关闭重开—读取，包含输入/返回值隔离、无故障状态、发布失败重试。演示真实跨层批次结果，以及更正协变量/批次后重开执行旧计划、读取旧报告。

沿现有 .pointwise-runtime.json 提供实际核验与演示，保留 version=1、kind="cli"、setup 的 argv 列表、verify/demo 的 argv 数组格式；verify 要执行原回归及新增断言，任一失败非零退出。demo 展示上述真实业务结果，不只输出成功提示。可扩展 run.py 或用其他真实入口接通清单；不新增前端、预测、基线生存曲线、正则化或模型选择目标。
