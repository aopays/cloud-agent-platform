"""Run repeatable three-round requirement-discovery scenarios against the local API."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    category: str
    requirement: str
    context: str
    answers: tuple[str, str, str]
    domain_keywords: tuple[str, ...]


SCENARIOS = (
    Scenario(
        "ECOM-OVERSELL",
        "电商-库存防超卖",
        "做一个能减少超卖的电商库存软件",
        "国内多平台零售，先做库存中心，不替换现有 ERP 和 WMS。",
        (
            "用户是电商运营、仓库和客服；淘宝、京东、自营商城共享约20万SKU，秒杀峰值每秒3000次库存请求。",
            "下单先预占，支付后扣减，取消或超时释放；调拨、盘点和退货会修正库存，不能出现负可售库存。",
            "要对接ERP、WMS和三个销售渠道；库存接口P99小于100毫秒，账实差异可追踪，六周交付第一版。",
        ),
        ("库存预占", "库存流水", "SKU", "超卖", "幂等", "WMS"),
    ),
    Scenario(
        "ECOM-SETTLEMENT",
        "电商-商家结算",
        "给平台做一个商家对账结算系统",
        "平台型电商，先支持人民币和境内商家。",
        (
            "用户是平台财务、商家财务和运营；约10万商家，每天200万订单，需要日对账、月结算。",
            "账单包含订单、退款、佣金、平台补贴、商家券、运费和罚款；差异需要申诉、复核和审计。",
            "对接订单、支付、退款、银行和ERP；结算批次必须幂等，可重跑但不能重复付款，数据保留七年。",
        ),
        ("账单", "结算批次", "佣金", "退款", "对账差异", "重复付款"),
    ),
    Scenario(
        "ECOM-RETURNS",
        "电商-退换货",
        "做一个电商退换货软件",
        "B2C 自营电商，第一版覆盖普通商品，不处理跨境和生鲜。",
        (
            "用户是消费者、客服、仓库质检和财务；支持仅退款、退货退款、换货三种申请。",
            "要校验售后时效、商品状态和责任原因；仓库收货质检后触发退款，异常单进入人工审核。",
            "对接订单、支付、物流、WMS和风控；消费者能查进度，退款状态必须可追踪，目标八周上线。",
        ),
        ("售后单", "逆向物流", "质检", "退款", "换货", "风控"),
    ),
    Scenario(
        "LOGISTICS-DRIVER",
        "物流-司机排班",
        "设计一个物流司机排班用的软件",
        "城市配送，第一版六周交付。",
        (
            "调度员和司机使用，100名司机、80辆车、10个区域，按天生成次日班表，优先准时和公平。",
            "必须满足驾照车型、连续驾驶和休息规则；请假、车辆故障、临时加单触发局部重排。",
            "对接TMS和GPS；调度员用Web，司机用手机端；首次求解60秒内，局部重排10秒内。",
        ),
        ("班次", "司机", "车辆", "时间窗", "局部重排", "OR-Tools"),
    ),
    Scenario(
        "SAAS-SUPPORT",
        "SaaS-工单分流",
        "做个能自动分客服工单的软件",
        "企业 SaaS 客服中心，只提供分流建议，不自动回复客户。",
        (
            "客服主管和一线客服使用；每天约5万封邮件和在线工单，按产品、语言、优先级和客户等级分配。",
            "P0故障和大客户投诉要立即升级；重复工单合并，误分后允许人工改派并反馈给规则。",
            "对接邮件、在线客服、CRM和值班系统；95%的工单30秒内完成分类，敏感信息不能进入普通日志。",
        ),
        ("工单", "优先级", "升级", "改派", "SLA", "CRM"),
    ),
    Scenario(
        "MANUFACTURING-MAINTENANCE",
        "制造-设备维护",
        "给工厂做一个设备维护软件",
        "单工厂试点，先覆盖关键生产线。",
        (
            "设备工程师、维修人员和生产主管使用；约500台设备，需要点检、保养、故障报修和备件管理。",
            "设备按运行小时或日历生成保养计划；停机故障自动升级，维修完成要记录原因、措施和验证结果。",
            "对接MES、传感器平台和备件库；关键设备故障5秒内告警，离线网络恢复后数据必须补传。",
        ),
        ("设备", "点检", "保养计划", "故障", "备件", "MES"),
    ),
    Scenario(
        "HEALTH-APPOINTMENT",
        "医疗-门诊预约",
        "设计一个医院挂号排队软件",
        "区域门诊试点，系统只辅助排队，不给出诊断和治疗建议。",
        (
            "患者、导诊、医生和窗口人员使用；支持预约、现场挂号、签到、叫号和过号处理。",
            "急诊和特殊患者按医院规则优先；医生停诊要批量通知和改约，任何人工插队必须记录原因。",
            "对接HIS、医生排班和短信；高峰每分钟200次签到，患者隐私按最小权限访问并记录审计。",
        ),
        ("号源", "签到", "叫号", "停诊", "改约", "HIS"),
    ),
    Scenario(
        "EDU-TIMETABLE",
        "教育-课程排课",
        "做一个学校自动排课系统",
        "一所中学试点，一个学期约60个班。",
        (
            "教务、年级主任和教师使用；要安排班级、教师、课程、教室和单双周课时。",
            "教师和教室不能冲突，体育实验课有场地要求，主课尽量不连排，教师可提交不可用时间。",
            "支持人工拖拽、冲突解释和版本发布；3000节课在2分钟内生成候选课表，并导出到教务系统。",
        ),
        ("课程", "教师", "教室", "课时", "冲突", "课表版本"),
    ),
    Scenario(
        "PROPERTY-WORKORDER",
        "物业-维修工单",
        "给小区做一个报修派单软件",
        "物业公司管理20个小区，先做微信端和管理后台。",
        (
            "业主、客服、维修人员和物业主管使用；业主上传文字图片，客服确认后按技能和小区派单。",
            "水电安全类立即升级；维修人员接单、到场、报价、完工，业主验收，争议单由主管处理。",
            "需要消息通知、地图定位和材料费用记录；普通工单5分钟内派出，所有状态变化保留审计。",
        ),
        ("报修", "派单", "到场", "完工", "验收", "维修人员"),
    ),
    Scenario(
        "RETAIL-PROCUREMENT",
        "零售-门店补货",
        "做一个连锁餐饮自动补货软件",
        "200家门店和3个配送中心，先覆盖常温和冷藏原料。",
        (
            "门店店长、采购和配送中心使用；根据销量、库存、在途、保质期和活动预测未来三天需求。",
            "低于安全库存生成建议单，临期优先消耗；门店可调整但要说明原因，缺货按门店优先级分配。",
            "对接POS、ERP、仓储和供应商；每天凌晨批量计算，单店也能实时重算，目标把缺货率降到2%以下。",
        ),
        ("补货建议", "安全库存", "保质期", "缺货", "采购单", "POS"),
    ),
    Scenario(
        "WAREHOUSE-PICKING",
        "仓储-拣货优化",
        "做一个仓库拣货更快的软件",
        "电商仓库试点，不改造现有自动化设备。",
        (
            "波次管理员和拣货员使用；仓库有5万货位、日均10万订单，支持单品、多品和大件订单。",
            "订单按承诺时间、库区和容器容量组波次；缺货、货位锁定和设备故障要重新规划但避免重复拣。",
            "对接WMS、电子标签和手持终端；波次5分钟内生成，路径可解释，扫描校验避免错拣漏拣。",
        ),
        ("波次", "货位", "拣货路径", "容器", "缺货", "WMS"),
    ),
    Scenario(
        "CONSTRUCTION-SAFETY",
        "工程-安全巡检",
        "给工地做一个安全检查软件",
        "多个项目部使用，移动端需要弱网可用。",
        (
            "安全员、整改负责人和项目经理使用；按模板巡检，上传照片和位置，发现隐患后生成整改任务。",
            "重大隐患立即停工升级；整改要有期限、复查和关闭，逾期逐级通知，删除证据需要审批。",
            "支持离线采集、联网同步和公司级统计；照片保留三年，权限按项目隔离，关键操作不可篡改。",
        ),
        ("巡检", "隐患", "整改", "复查", "停工", "离线"),
    ),
    Scenario(
        "HR-INTERVIEW",
        "人力-面试协调",
        "做一个自动约面试的软件",
        "公司内部招聘团队使用，第一版不自动淘汰候选人。",
        (
            "招聘专员、面试官和候选人使用；根据岗位轮次、面试官技能、日历和候选人时区安排面试。",
            "支持候选时间投票、冲突检测、改期和取消；临近面试提醒，面试官缺席时自动寻找替代人。",
            "对接ATS、企业日历和视频会议；个人信息最小化展示，安排结果30秒内返回并保留沟通记录。",
        ),
        ("候选人", "面试官", "日历", "时区", "改期", "ATS"),
    ),
    Scenario(
        "AGRI-IRRIGATION",
        "农业-智能灌溉",
        "做一个农田自动浇水的软件",
        "5000亩试点，设备网络不稳定，自动控制必须可以人工接管。",
        (
            "农场经理和现场人员使用；根据地块、作物、土壤湿度、天气和水源容量制定灌溉计划。",
            "设备离线或传感器异常时不能盲目执行；高温干旱优先，降雨前暂停，任何远程开阀都要有安全上限。",
            "对接传感器、气象和阀门网关；弱网下本地策略继续运行，告警一分钟内送达，操作有完整审计。",
        ),
        ("地块", "土壤湿度", "灌溉计划", "阀门", "传感器", "人工接管"),
    ),
    Scenario(
        "ELDERCARE-SERVICE",
        "养老-上门服务调度",
        "做一个老人上门服务安排软件",
        "社区养老机构试点，仅做服务调度，不提供医疗诊断。",
        (
            "调度员、服务人员、老人和家属使用；安排助餐、清洁、陪诊和康复辅助等服务。",
            "匹配服务资质、时间窗、距离和老人偏好；服务人员请假或老人取消时重排，紧急情况转人工热线。",
            "需要手机签到、家属通知和服务评价；位置及健康相关信息严格授权，排班变更5分钟内完成。",
        ),
        ("老人", "服务人员", "时间窗", "资质", "签到", "家属"),
    ),
)


def _quality(report: str, scenario: Scenario) -> dict[str, Any]:
    generated_part = report.split("## 4.", maxsplit=1)[-1]
    structure_checks = {
        "scope_or_roles": any(term in report for term in ("用户角色", "MVP 功能", "MVP功能")),
        "process_or_rules": any(term in report for term in ("业务流程", "业务规则", "核心流程")),
        "data_model": "数据模型" in report,
        "api_or_architecture": "技术架构" in report and ("API" in report or "/v1/" in report),
        "security_and_nfr": "安全" in report
        and any(term in report for term in ("非功能", "性能", "可用性")),
        "acceptance": "验收标准" in report,
    }
    keyword_hits = [word for word in scenario.domain_keywords if word in generated_part]
    structure_score = sum(structure_checks.values())
    domain_score = 2 if len(keyword_hits) >= 4 else 1 if len(keyword_hits) >= 2 else 0
    implementation_score = structure_score * 2 + domain_score * 4
    return {
        "structure": structure_checks,
        "structurePassed": structure_score,
        "structureTotal": len(structure_checks),
        "domainKeywordHits": keyword_hits,
        "domainKeywordTotal": len(scenario.domain_keywords),
        "minimumLength": len(report) >= 1_000,
        "implementationScore": implementation_score,
        "implementationMax": len(structure_checks) * 2 + 8,
        "qualityPassed": len(report) >= 1_000 and structure_score >= 5 and domain_score == 2,
    }


def _run_scenario(client: httpx.Client, scenario: Scenario, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    started = time.monotonic()
    created = client.post(
        "/v1/discovery-sessions",
        headers=headers,
        json={"requirement": scenario.requirement, "context": scenario.context},
    )
    created.raise_for_status()
    session = created.json()
    message_codes: list[int] = []
    for answer in scenario.answers:
        continued = client.post(
            f"/v1/discovery-sessions/{session['id']}/messages",
            headers=headers,
            json={"content": answer},
        )
        continued.raise_for_status()
        message_codes.append(continued.status_code)
        session = continued.json()
    ready_status = session["status"]
    finalized = client.post(
        f"/v1/discovery-sessions/{session['id']}/finalize",
        headers=headers,
    )
    finalized.raise_for_status()
    session = finalized.json()
    downloaded = client.get(session["artifact"]["downloadUrl"], headers=headers)
    downloaded.raise_for_status()
    report = downloaded.text
    technical_checks = {
        "created201": created.status_code == 201,
        "threeMessages200": message_codes == [200, 200, 200],
        "readyAfterThreeRounds": ready_status == "READY",
        "finalized": session["status"] == "FINALIZED",
        "artifactDownloaded": downloaded.status_code == 200,
        "answersPreserved": all(answer in report for answer in scenario.answers),
        "notTodoReport": "# TODO Report" not in report,
    }
    quality = _quality(report, scenario)
    return {
        "id": scenario.scenario_id,
        "category": scenario.category,
        "requirement": scenario.requirement,
        "sessionId": session["id"],
        "artifactId": session["artifact"]["id"],
        "downloadUrl": session["artifact"]["downloadUrl"],
        "reportChars": len(report),
        "durationMs": round((time.monotonic() - started) * 1_000),
        "technicalChecks": technical_checks,
        "technicalPassed": all(technical_checks.values()),
        **quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default="local-demo-token")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        results = [_run_scenario(client, scenario, args.token) for scenario in SCENARIOS]
    summary = {
        "scenarioCount": len(results),
        "conversationRounds": len(results) * 3,
        "ecommerceCount": sum(item.category.startswith("电商-") for item in SCENARIOS),
        "technicalPassed": sum(item["technicalPassed"] for item in results),
        "qualityPassed": sum(item["qualityPassed"] for item in results),
        "averageDurationMs": round(sum(item["durationMs"] for item in results) / len(results)),
        "averageReportChars": round(sum(item["reportChars"] for item in results) / len(results)),
        "results": results,
    }
    output = (
        summary
        if not args.summary_only
        else {key: value for key, value in summary.items() if key != "results"}
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if summary["technicalPassed"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
