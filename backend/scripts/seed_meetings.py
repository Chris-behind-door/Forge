#!/usr/bin/env python3
"""
Seed demo data for the Meetings feature.
Usage: python scripts/seed_meetings.py
Requires backend running on port 8765.
"""

import sys
import httpx

BASE = "http://127.0.0.1:8765"


def main():
    # Health check
    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
    except Exception:
        print("❌ 后端未运行，请先启动应用")
        sys.exit(1)

    # Step 0: Clean up existing projects with similar names
    print("🧹 清理旧数据...")
    projects = httpx.get(f"{BASE}/projects").json()
    for p in projects:
        if "丁二烯" in p["name"] or "小爪" in p["name"] or "test" in p.get("name", "").lower():
            httpx.delete(f"{BASE}/projects/{p['id']}")
            print(f"  删除项目: {p['name']}")

    # Step 1: Create project
    print("\n📁 创建项目...")
    proj = httpx.post(f"{BASE}/projects", json={
        "name": "丁二烯项目",
        "description": "2#丁二烯装置岩土工程审查及桩基设计",
    }).json()
    pid = proj["id"]
    print(f"  ✓ {proj['name']} ({pid})")

    # Step 2: Create meetings
    print("\n📅 创建会议...")
    meetings_data = [
        {
            "title": "第1次岩土工程审查会",
            "date": "2026-03-10",
            "raw_text": (
                "会议主题：浙石化二期丁二烯装置场地岩土工程参数审查\n\n"
                "与会单位：建设单位、设计院、勘察单位（宁波冶金勘察设计院、浙江有色、浙江物探、上海昌发）\n\n"
                "会议要点：\n"
                "1. 各勘察单位汇报了勘察补充说明的主要内容，重点针对场地填土层厚度、软土分布及负摩阻力问题进行了说明。\n"
                "2. 设计院提出桩基负摩阻力计算需要明确中性点位置，要求勘察单位提供各土层的极限侧阻力标准值和极限端阻力标准值。\n"
                "3. 经讨论，一致认为应按《建筑桩基技术规范》JGJ 94-2008考虑负摩阻力影响，中性点深度取桩长入土深度的0.5~0.6倍。\n"
                "4. 关于抗震设防参数，确认为8度（0.2g），第一组，场地类别III类。"
            ),
        },
        {
            "title": "第2次设计协调会",
            "date": "2026-03-25",
            "raw_text": (
                "会议主题：桩基设计方案调整协调\n\n"
                "会议要点：\n"
                "1. 根据勘察补充说明，场地存在较厚填土层（最大厚度达12m），设计院提出需要重新评估桩基方案。\n"
                "2. 原方案采用φ600 PHC管桩，考虑到负摩阻力影响较大，决定改用φ800钻孔灌注桩，桩长适当加长。\n"
                "3. 负摩阻力系数取值：填土层取0.30，淤泥质土取0.20，粉质粘土取0.25。\n"
                "4. 单桩承载力特征值暂按2500kN估算，需施工图阶段进一步验算。\n"
                "5. 桩端持力层选用⑥层粉砂层，进入持力层深度不小于2D。"
            ),
        },
        {
            "title": "第3次技术交底会",
            "date": "2026-04-15",
            "raw_text": (
                "会议主题：桩基施工技术交底及要求确认\n\n"
                "会议要点：\n"
                "1. 施工单位提出泥浆护壁成孔工艺在填土层中容易塌孔，经讨论同意采用全套管回转钻进工艺。\n"
                "2. 桩基检测方案确定为：全部进行低应变检测，30%进行声波透射法检测，5根进行静载试验。\n"
                "3. 对于单桩承载力特征值，考虑到实际桩长可能因地质条件变化而调整，同意施工中根据实际地层情况在±3m范围内调整桩长，但需经设计确认。\n"
                "4. 关于负摩阻力计算，确认采用中性点法，中性点深度比取0.55，下拉荷载标准值按各勘察单位提供的参数取不利值。\n"
                "5. 超灌高度不小于1.0m，凿除浮浆后桩顶标高应满足设计要求。"
            ),
        },
    ]

    mtg_ids = []
    for m in meetings_data:
        resp = httpx.post(f"{BASE}/projects/{pid}/meetings", json=m).json()
        mtg_ids.append(resp["id"])
        print(f"  ✓ {m['title']} ({resp['id']})")

    # Step 3: Create resolutions
    print("\n📝 创建决议...")
    resolutions_data = {
        # Meeting 1
        mtg_ids[0]: [
            {
                "content": "桩基负摩阻力计算按《建筑桩基技术规范》JGJ 94-2008执行，中性点深度取桩长入土深度的0.5~0.6倍，具体取值根据各勘察单位提供的地层参数确定。",
                "index": 1,
                "status": "superseded",
            },
            {
                "content": "抗震设防参数确认为8度（0.2g），设计地震分组第一组，场地类别III类，特征周期0.45s。",
                "index": 2,
                "status": "active",
            },
            {
                "content": "要求各勘察单位于两周内提交正式的勘察补充说明文件，明确各土层的桩基设计参数。",
                "index": 3,
                "status": "active",
            },
        ],
        # Meeting 2
        mtg_ids[1]: [
            {
                "content": "桩基方案由φ600 PHC管桩调整为φ800钻孔灌注桩，桩长根据持力层深度确定，以⑥层粉砂层为桩端持力层，进入持力层深度不小于2D。",
                "index": 1,
                "status": "amended",
            },
            {
                "content": "负摩阻力系数取值确认为：填土层0.30，淤泥质土0.20，粉质粘土0.25。单桩承载力特征值暂按2500kN估算。",
                "index": 2,
                "status": "active",
            },
        ],
        # Meeting 3
        mtg_ids[2]: [
            {
                "content": "抗震设防参数补充说明：场地类别III类，设计特征周期0.45s。场地存在液化土层（②层粉砂），液化等级为轻微，桩基设计可不考虑液化影响。",
                "index": 1,
                "status": "active",
            },
            {
                "content": "桩基施工工艺调整为全套管回转钻进工艺（替代原泥浆护壁方案），以应对填土层塌孔风险。桩长可在±3m范围内根据实际地层调整，但需设计确认。",
                "index": 2,
                "status": "active",
            },
            {
                "content": "桩基检测方案：全部低应变检测、30%声波透射法检测、5根静载试验。超灌高度不小于1.0m。",
                "index": 3,
                "status": "active",
            },
        ],
    }

    res_map = {}  # (meeting_idx, res_index) -> res_id
    for mtg_id, res_list in resolutions_data.items():
        mtg_idx = mtg_ids.index(mtg_id)
        for rd in res_list:
            resp = httpx.post(f"{BASE}/meetings/{mtg_id}/resolutions", json=rd).json()
            res_map[(mtg_idx, rd["index"])] = resp["id"]
            print(f"  ✓ [{meetings_data[mtg_idx]['title']}] 决议{rd['index']}: {resp['id']} ({rd['status']})")

    # Step 4: Create relations
    print("\n🔗 创建关联关系...")
    relations = [
        {
            "desc": "第2次会议决议1 SUPERSEDES 第1次会议决议1",
            "from_id": res_map[(1, 1)],
            "to_id": res_map[(0, 1)],
            "relation_type": "SUPERSEDES",
            "reason": "桩基方案由PHC管桩改为灌注桩，原负摩阻力计算方法决议被新方案替代",
        },
        {
            "desc": "第3次会议决议2 AMENDS 第2次会议决议1",
            "from_id": res_map[(2, 2)],
            "to_id": res_map[(1, 1)],
            "relation_type": "AMENDS",
            "change_summary": "补充施工工艺要求（全套管回转钻进），并允许桩长±3m调整",
        },
        {
            "desc": "第3次会议决议1 SUPPLEMENTS 第1次会议决议2",
            "from_id": res_map[(2, 1)],
            "to_id": res_map[(0, 2)],
            "relation_type": "SUPPLEMENTS",
            "supplement_content": "补充场地液化评价结论及对桩基设计的影响说明",
        },
    ]

    for rel in relations:
        resp = httpx.post(f"{BASE}/resolutions/relations", json=rel)
        print(f"  ✓ {rel['desc']}")

    print("\n✅ Demo 数据注入完成！打开应用查看「会议纪要」页面。")


if __name__ == "__main__":
    main()
