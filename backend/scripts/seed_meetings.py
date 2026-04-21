"""
Seed script: inject demo meeting data for 丁二烯项目.

Usage:
    cd backend && python scripts/seed_meetings.py
"""

import sys
from pathlib import Path

# Allow running from backend/ or project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

BASE = "http://127.0.0.1:8765"


def main():
    client = httpx.Client(base_url=BASE, timeout=15)

    # Health check
    r = client.get("/health")
    assert r.status_code == 200, f"Backend not healthy: {r.status_code}"
    print("✓ Backend is healthy")

    # --- 1. Create project ---
    r = client.post("/projects", json={"name": "丁二烯项目", "description": "丁二烯装置岩土工程与基础设计"})
    assert r.status_code in (200, 201, 409), f"Create project failed: {r.text}"
    project = r.json() if r.status_code != 409 else _find_project(client, "丁二烯项目")
    pid = project["id"]
    print(f"✓ Project: {project['name']} ({pid})")

    # --- 2. Create meetings ---
    meetings_data = [
        {
            "title": "第1次岩土工程审查会",
            "date": "2026-03-10",
            "raw_text": (
                "一、会议背景\n"
                "本次会议针对丁二烯装置岩土工程勘察报告进行审查，重点讨论场地土层分布、地下水条件及地基处理方案。\n\n"
                "二、参会人员\n"
                "建设单位：张工、李工\n设计单位：王总工、赵工\n勘察单位：刘工\n\n"
                "三、讨论内容\n"
                "1. 场地地基土主要为粉质粘土和砂层，承载力特征值 fak=180kPa。\n"
                "2. 地下水位埋深约2.5m，需考虑地下水对基础施工的影响。\n"
                "3. 厂区部分地段存在软弱下卧层，需进行负摩阻力验算。\n"
                "4. 抗震设防烈度为7度，设计基本地震加速度0.15g。\n\n"
                "四、决议\n"
                "（见下方决议卡片）"
            ),
            "resolutions": [
                {
                    "content": "场地地基承载力特征值取 fak=180kPa，采用天然地基方案时需进行详细验算，重点复核软弱下卧层承载力。对于荷载较大的构筑物区域（如塔器基础），应采用桩基础方案。",
                    "index": 1,
                },
                {
                    "content": "桩基设计负摩阻力计算采用《建筑桩基技术规范》(JGJ 94-2008) 第5.4节方法，中性点深度按 ln=0.8l0 估算（l0 为桩周软弱土层下限深度），负摩阻力标准值 qsi^n 按现场静力触探成果取值，粉质粘土层取 20kPa，淤泥质粘土层取 15kPa。",
                    "index": 2,
                },
                {
                    "content": "抗震设计采用振型分解反应谱法，场地类别为Ⅱ类，特征周期 Tg=0.35s。塔器等高耸构筑物需补充时程分析验算。",
                    "index": 3,
                },
            ],
        },
        {
            "title": "第2次设计协调会",
            "date": "2026-03-25",
            "raw_text": (
                "一、会议背景\n"
                "根据第1次审查会决议，设计单位完成了桩基初步设计方案。本次会议协调桩基选型与施工方案的衔接问题。\n\n"
                "二、讨论内容\n"
                "1. 原方案采用 PHC 管桩，但场地砂层较厚，沉桩困难。\n"
                "2. 建议改为钻孔灌注桩方案，桩径800mm，桩长25m。\n"
                "3. 负摩阻力计算需结合新桩型重新验算。\n"
                "4. 承台尺寸和配筋需优化。\n\n"
                "三、决议\n"
                "（见下方决议卡片）"
            ),
            "resolutions": [
                {
                    "content": "桩基方案由 PHC 管桩调整为钻孔灌注桩，桩径 D=800mm，桩长 L=25m，混凝土强度等级 C30，以中风化砂岩为持力层，入岩深度不小于1.0D。单桩竖向承载力特征值 Ra 经验算取 2800kN。",
                    "index": 1,
                },
                {
                    "content": "承台厚度统一取 1200mm，混凝土等级 C35，保护层厚度 50mm（桩头嵌入部分）。承台配筋按《建筑地基基础设计规范》(GB 50007) 附录计算，底筋双向 HRB400 φ25@150。",
                    "index": 2,
                },
            ],
        },
        {
            "title": "第3次技术交底会",
            "date": "2026-04-15",
            "raw_text": (
                "一、会议背景\n"
                "施工图设计基本完成，本次会议向施工单位进行技术交底，明确施工控制要点。\n\n"
                "二、参会人员\n"
                "建设单位：张工\n设计单位：王总工\n施工单位：陈经理、孙工\n监理单位：周工\n\n"
                "三、讨论内容\n"
                "1. 钻孔灌注桩施工质量控制要点。\n"
                "2. 负摩阻力区域桩身加强措施。\n"
                "3. 地下水控制方案。\n"
                "4. 抗震构造措施。\n\n"
                "四、决议\n"
                "（见下方决议卡片）"
            ),
            "resolutions": [
                {
                    "content": "钻孔灌注桩施工严格执行《建筑桩基技术规范》(JGJ 94-2008) 要求：孔径偏差不超过 ±50mm，孔深不小于设计值，沉渣厚度不超过 50mm。灌注前需二次清孔，泥浆比重控制在 1.05~1.15 之间。桩身完整性检测采用低应变法，检测比例 100%。",
                    "index": 1,
                },
                {
                    "content": "负摩阻力区域（地面以下 0~15m 范围）桩身采用加强措施：纵向钢筋通长配置，并在该区段增设 HRB400 φ16@200 的螺旋箍筋，箍筋保护层厚度不小于 50mm。桩顶 3D 范围内箍筋加密为 φ16@100。",
                    "index": 2,
                },
                {
                    "content": "施工期间地下水位控制在基础底面以下 0.5m，采用轻型井点降水。基坑开挖边坡坡率 1:1.5，深度超过 3m 时需放坡并设置临时支护。开挖过程中加强监测，周边建筑物沉降观测点间距不大于 20m。",
                    "index": 3,
                },
            ],
        },
    ]

    created_meetings = []
    for mtg in meetings_data:
        r = client.post(f"/projects/{pid}/meetings", json={
            "title": mtg["title"],
            "date": mtg["date"],
            "raw_text": mtg["raw_text"],
        })
        assert r.status_code in (200, 201), f"Create meeting failed: {r.text}"
        meeting = r.json()
        mid = meeting["id"]
        print(f"✓ Meeting: {meeting['title']} ({mid})")

        created_resolutions = []
        for res in mtg["resolutions"]:
            r = client.post(f"/meetings/{mid}/resolutions", json={
                "content": res["content"],
                "index": res["index"],
                "status": "active",
            })
            assert r.status_code in (200, 201), f"Create resolution failed: {r.text}"
            resolution = r.json()
            created_resolutions.append(resolution)
            print(f"  ✓ Resolution {res['index']}: {resolution['id']}")

        created_meetings.append({"meeting": meeting, "resolutions": created_resolutions})

    # --- 3. Create relations ---
    # 第2次会议决议1 SUPERSEDES 第1次会议决议1
    rel1 = client.post("/resolutions/relations", json={
        "from_id": created_meetings[1]["resolutions"][0]["id"],
        "to_id": created_meetings[0]["resolutions"][0]["id"],
        "relation_type": "SUPERSEDES",
        "meeting_id": created_meetings[1]["meeting"]["id"],
        "reason": "桩基方案由PHC管桩调整为钻孔灌注桩，原天然地基/管桩方案决议不再适用",
        "change_summary": "桩型由PHC管桩改为钻孔灌注桩，桩径800mm，桩长25m",
    })
    assert rel1.status_code == 200, f"Create relation failed: {rel1.text}"
    print("✓ Relation: M2-R1 SUPERSEDES M1-R1")

    # 第3次会议决议2 AMENDS 第2次会议决议1
    rel2 = client.post("/resolutions/relations", json={
        "from_id": created_meetings[2]["resolutions"][1]["id"],
        "to_id": created_meetings[1]["resolutions"][0]["id"],
        "relation_type": "AMENDS",
        "meeting_id": created_meetings[2]["meeting"]["id"],
        "reason": "增加负摩阻力区段桩身加强措施要求",
        "change_summary": "补充0~15m范围螺旋箍筋加强和桩顶加密要求",
    })
    assert rel2.status_code == 200, f"Create relation failed: {rel2.text}"
    print("✓ Relation: M3-R2 AMENDS M2-R1")

    # 第3次会议决议1 SUPPLEMENTS 第1次会议决议2
    rel3 = client.post("/resolutions/relations", json={
        "from_id": created_meetings[2]["resolutions"][0]["id"],
        "to_id": created_meetings[0]["resolutions"][1]["id"],
        "relation_type": "SUPPLEMENTS",
        "meeting_id": created_meetings[2]["meeting"]["id"],
        "reason": "对钻孔灌注桩施工质量提出具体控制要求，补充原决议的计算方法",
        "supplement_content": "孔径偏差±50mm，沉渣厚度≤50mm，低应变检测100%",
    })
    assert rel3.status_code == 200, f"Create relation failed: {rel3.text}"
    print("✓ Relation: M3-R1 SUPPLEMENTS M1-R2")

    print("\n✅ Seed data created successfully!")


def _find_project(client: httpx.Client, name: str) -> dict:
    r = client.get("/projects")
    for p in r.json():
        if p["name"] == name:
            return p
    raise RuntimeError(f"Project '{name}' not found")


if __name__ == "__main__":
    main()
