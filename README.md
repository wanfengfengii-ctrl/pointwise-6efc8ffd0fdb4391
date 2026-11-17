# 北岸设备可靠性归档

Python 3.11 标准库项目。记录员提交台架运行记录及晚到更正，分析员冻结指定知识修订，可靠性工程师读取固定的分层人时、负载暴露、故障数及描述性故障率，用于核对试验覆盖和安排后续试验。归档不控制设备。

## 一天的工作

1. 从台架日志整理设备、批次、分层和完整运行区间，形成替换请求。
2. 规范化精确数值并检查整批时间线；非法请求不改变归档。
3. 原子接纳请求，获得修订回执；重放同内容请求取得原回执。
4. 指定知识修订和设备集合，解析全部成员并冻结完整依据。
5. 从固定队列计算实际运行人时、负载暴露和设备故障数。
6. 构建完整正文，原子发布固定报告。
7. 读取报告并按层比较更正前后的覆盖差值。
8. 关闭重开，读取原报告；失败发布按原队列重试。

## 运行

在项目根目录运行，无安装依赖：

```sh
python3.11 -B run.py verify
python3.11 -B -m unittest discover -s tests -v
python3.11 -B run.py demo --db demo.sqlite3
```

demo 数据库必须显式指定且为文件数据库。首次打开只创建模式和空修订0，不导入设备。demo 使用 examples/daily.json 和 examples/correction.json 中的稳定请求ID；重复运行重放原修订，不覆盖后来用户更正，但会新建队列和报告。相同请求ID的内容冲突会抛错，不清空数据库。模式版本不支持时拒绝打开。数据库所在父目录须已存在。

verify 运行全部六个测试文件，失败退出码为1；支持真实测试名，例如：

```sh
python3.11 -B run.py verify test_daily.TestDaily.test_exact_exposure test_publish.TestPublish.test_atomic_publication
```

测试仅使用内存数据库或测试自己的临时目录。发布失败场景通过 SQLite 触发器产生真实存储异常。demo 在完成断言后输出 POINTWISE_SCENARIO JSON，分数以[分子,分母]显示。

## 公开 Python API

包为命名空间包，直接在项目根目录导入：

```python
from fractions import Fraction
from reliability.archive.store import Archive
from reliability.records.revisions import RecordService
from reliability.cohorts.snapshots import CohortService
from reliability.analysis.describe import DescriptionService
from reliability.reports.publish import ReportPublisher
from reliability.reports.read import ReportReader
from reliability.reports.compare import ReportComparator

with Archive.open("lab.sqlite3") as archive:
    records = RecordService(archive)
    receipt = records.apply("day-1", {
        "A": {"batch_id": "lot1", "stratum": "alpha", "intervals": [
            {"start": 0, "stop": 2, "load": 3, "failed": False},
            {"start": 3, "stop": 4, "load": 5, "failed": True}
        ]}
    })
    cohort = CohortService(archive).freeze(receipt.revision, ["A"])
    result = DescriptionService(archive).describe(cohort["cohort_id"])
    assert result.strata[0]["person_time"] == Fraction(3)
    assert result.strata[0]["load_exposure"] == Fraction(11)
    report_id = ReportPublisher(archive).publish(cohort["cohort_id"])
    report = ReportReader(archive).read(report_id)
    assert report["strata"][0]["rate"] == Fraction(1, 3)
    delta = ReportComparator(archive).compare(report_id, report_id)
    assert delta["strata"][0]["person_time"] == 0
```

- RecordService.apply(request_id, device_intervals) 返回 ApplyReceipt，字段 request_id、revision、device_ids。列表中的设备是本请求的替换范围，batch_id仅是实验归属，未列设备沿用历史状态。空批次合法，新的请求仍产生修订。相同ID及完整规范内容重放返回原回执；异内容抛 ValueError。设备、区间顺序及等值分数不影响身份。RecordService.revision 返回当前头，get_revision(revision) 返回指定历史设备映射。
- CohortService.freeze(revision, device_ids) 返回字典 cohort_id、revision、members；选择去重并按设备ID排序。load_snapshot(cohort_id) 返回不可变 CohortSnapshot，summary() 生成独立可修改摘要。未知修订或成员抛 KeyError，整次不创建队列。
- DescriptionService.describe(cohort_id) 返回 DescriptiveResult，字段 cohort_id、revision、members、strata。结果列表可修改，不影响后续调用。未知队列抛 KeyError，不创建报告。
- ReportPublisher.publish(cohort_id) 返回整数报告ID。报告头、正文和有序分层行同时提交；存储异常原样传播并全部回滚，旧报告不变。重试不去重，可生成新的完整报告。
- ReportReader.read(report_id) 返回独立字典，含 report_id、format_version、basis、cohort_id、revision、members、strata。仅读取持久正文，不重新计算。未知报告抛 KeyError，不完整或不支持的存储正文抛 ValueError。
- ReportComparator.compare(left_report_id, right_report_id) 返回左右ID、basis及strata。按分层并集对齐，单边缺失总量按零处理，差值为右减左。仅比较人时、暴露及故障数；口径不相容抛 ValueError，未知报告抛 KeyError。

Archive.open(path) 支持文件路径、Path和 :memory:；后者不能跨关闭恢复。close() 可重复调用，关闭后的 connection 访问抛 RuntimeError。connection 是供集成与存储诊断使用的 SQLite 连接；应用业务更正应通过 apply。写入辅助查询需要外层事务，不自行提交；不支持嵌套事务。

## 数据与计算口径

设备、批次、分层和请求ID是非空字符串。设备和区间字段完整且不得多传字段。时间单位为小时，区间为(start,stop]。时间、负载接受整数或 Fraction，不接受布尔值和浮点数；failed必须为bool。JSON样例的分数采用两个非布尔整数[分子,非零分母]，经 run.decode_submission 转换后调用API。数值不另加正负范围；每段必须start<stop。

同设备的区间可无序输入，接纳前排序；允许相邻及间隙，不允许重叠。每设备最多一次故障，且仅能发生在最后区间的stop。空区间列表仍保留设备身份及分层。每个请求中全部设备校验成功才持久化，任一非法字段、重叠或故障后记录使整批抛 ValueError。

人时为各段(stop-start)之和，负载暴露为各段(stop-start)*load之和；间隙不贡献。故障按设备计数，同批设备各自贡献。分层按名字排序；人时、暴露、非空故障率均为 Fraction，故障数为int。正人时无故障率为 Fraction(0)，零人时层率为 None；空队列没有分层。相邻等负载非故障段的拆分不改变这些描述性总量。计算没有随机性或浮点舍入。

样例daily的alpha人时2+1=3、暴露2*3+1*5=11、故障1、率1/3；beta人时2、暴露4、故障0、率0。更正后A进入gamma，运行2小时、暴露6、无故障；比较的alpha为(-3,-11,-1)、beta为(0,0,0)、gamma为(2,6,0)，三元顺序为人时、暴露、故障。旧报告重开后仍保留alpha的11及lot1依据。

## 状态及代码

records 的 devices/intervals/validation 负责独立规范值和时间线，requests/revisions 负责完整请求身份、原子接纳及历史读取。cohorts 的 selection/members/snapshots 固定完整来源，compile 交付不可变逐设备描述性输入。analysis 的 exposure/failures/strata/rates/describe 计算并交接精确结果。reports 的 build/content/publish/read/compare 构建、存取和解释固定正文。archive 的 schema/codec/transactions/store/queries 维护版本、精确编码、原子边界及历史查询。

修订、队列、报告分别拥有事务边界。来源更正只形成新修订，不修改旧队列或报告。正文固定源修订和成员依据；持久编码区分 Fraction、int、bool和None。重复初始化不重置ID、历史或用户内容。

## 确定性回归

tests/test_daily.py 核对间隙、手算分数、分层、同批两故障、拆分可加性、空队列及零人时层。
tests/test_records.py 核对整批拒绝、故障终止、相邻区间、非法类型、JSON零分母、规范重放及重开冲突。
tests/test_cohorts.py 核对完整选择、指定历史修订、稳定顺序及未知对象错误。
tests/test_corrections.py 核对冻结依据、层迁移并集、差值符号及不同业务口径拒绝。
tests/test_persistence.py 核对输入/输出别名、精确重开、禁止读取来源表时的固定报告读取、重复初始化及用户更正保留。
tests/test_publish.py 核对报告头/首层失败后的全回滚、旧报告保全、关闭重开重试和来源更正后原导出的固定队列重试。
