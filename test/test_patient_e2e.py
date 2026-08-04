# -*- coding: utf-8 -*-
"""
B-T2 端到端测试：浏览器（Playwright + 系统 Edge）患者管理全流程。
前置：uvicorn(8321) + vite dev(5173) 已启动（测试自检不可达则 skip）。
流程：登录 → 建档 → 列表显示 → 编辑 → 删除 → 后置清理（主库恢复干净）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

import urllib.request  # noqa: E402

E2E_USER = "e2e_doctor"
E2E_PWD = "E2e@Doctor2026"
FRONT_URL = "http://localhost:5173/"


def _api_alive() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8321/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _prepare_user():
    """主库幂等创建 e2e 医师用户（测试后清理）。"""
    import db
    from repo import Repository
    from security import SecurityManager
    conn = db.get_conn()
    repo = Repository(conn)
    sec = SecurityManager()
    if not repo.get_user_by_username(E2E_USER):
        repo.create_user(E2E_USER, sec.hash_password(E2E_PWD), "E2E医师", "医师")
    conn.close()


def _cleanup(before_ids: set):
    """后置清理：删测试期间新增且无业务记录的患者 + e2e 用户。"""
    import db
    conn = db.get_conn()
    now_ids = {r[0] for r in conn.execute("SELECT patient_id FROM patient").fetchall()}
    for pid in now_ids - before_ids:
        # 先删评估相关业务记录（评估后患者有记录，保护式设计不允许直接删）
        for tbl in ("assessment", "tcm_pattern", "risk_stratification", "alert",
                    "adherence_log", "prescription", "follow_up"):
            conn.execute(f"DELETE FROM {tbl} WHERE patient_id=?", (pid,))
        conn.execute("DELETE FROM procedure WHERE patient_id=?", (pid,))
        conn.execute("DELETE FROM patient WHERE patient_id=?", (pid,))
    conn.execute("DELETE FROM user WHERE username=?", (E2E_USER,))
    conn.commit()
    conn.close()


@unittest.skipUnless(_api_alive(), "API/前端服务未启动（需 uvicorn 8321 + vite 5173）")
class TestPatientE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import db
        conn = db.get_conn()
        cls._before_ids = {r[0] for r in conn.execute("SELECT patient_id FROM patient").fetchall()}
        conn.close()
        _prepare_user()

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._before_ids)

    def test_full_flow(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()

            # 1. 登录页
            page.goto(FRONT_URL)
            expect(page.locator("input[placeholder='用户名']")).to_be_visible()
            page.fill("input[placeholder='用户名']", E2E_USER)
            page.fill("input[placeholder='密码']", E2E_PWD)
            page.click("button[type='submit']")
            # 进入患者页（导航出现）
            expect(page.locator(".nav")).to_be_visible(timeout=8000)

            # 2. 建档
            name = "浏览器患者E2E"
            page.fill("input[placeholder='1960-01-01']", "1965-05-05")  # 出生日期
            page.fill("label:has-text('联系电话') input", "13999998888")
            page.fill("label:has-text('主管医师') input", "E2E医师")
            page.fill("label:has-text('姓名') input", name)
            page.click("button[type='submit']:has-text('建档')")
            # 列表出现该患者
            expect(page.locator(f"tbody >> text={name}")).to_be_visible(timeout=8000)

            # 3. 编辑
            row = page.locator("tr", has_text=name)
            row.locator("button:has-text('编辑')").click()
            # 表单回填后改名
            page.fill("label:has-text('姓名') input", name + "改")
            page.click("button[type='submit']:has-text('保存修改')")
            expect(page.locator("tbody >> text=" + name + "改")).to_be_visible(timeout=8000)

            # 4. 删除（confirm 自动接受）
            page.on("dialog", lambda d: d.accept())
            row2 = page.locator("tr", has_text=name + "改")
            row2.locator("button:has-text('删除')").click()
            # 等待列表刷新后该患者消失
            expect(page.locator(f"tbody >> text={name}改")).to_have_count(0, timeout=8000)

            browser.close()


@unittest.skipUnless(_api_alive(), "API/前端服务未启动（需 uvicorn 8321 + vite 5173）")
class TestAssessmentE2E(unittest.TestCase):
    """B-T3 浏览器 e2e：建档 → 评估录入（自动证型+分层）→ 结果回显。"""

    @classmethod
    def setUpClass(cls):
        import db
        conn = db.get_conn()
        cls._before_ids = {r[0] for r in conn.execute("SELECT patient_id FROM patient").fetchall()}
        conn.close()
        _prepare_user()

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._before_ids)

    def test_assessment_flow(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()

            # 登录
            page.goto(FRONT_URL)
            page.fill("input[placeholder='用户名']", E2E_USER)
            page.fill("input[placeholder='密码']", E2E_PWD)
            page.click("button[type='submit']")
            expect(page.locator(".nav")).to_be_visible(timeout=8000)

            # 建档（评估对象）
            name = "评估E2E患者"
            page.fill("label:has-text('姓名') input", name)
            page.click("button[type='submit']:has-text('建档')")
            expect(page.locator("tbody >> text=" + name)).to_be_visible(timeout=8000)

            # 进入评估页
            page.click("a:has-text('评估录入')")
            expect(page.locator("h2:has-text('评估录入')")).to_be_visible(timeout=8000)

            # 选患者 + 填指标 + 勾四诊
            page.select_option("label:has-text('患者') select", index=1)
            page.fill("label:has-text('LVEF(%)') input", "46")
            page.fill("label:has-text('6MWD(m)') input", "550")
            page.fill("label:has-text('PHQ-9') input", "5")
            # 勾选一个四诊项（如有）
            if page.locator(".checks input").count() > 0:
                page.locator(".checks input").first.check()

            # 提交 → 判定结果出现
            page.click("button[type='submit']:has-text('保存并判定')")
            expect(page.locator(".result")).to_be_visible(timeout=8000)
            expect(page.locator(".result >> text=危险分层")).to_be_visible()
            expect(page.locator(".result >> text=证型")).to_be_visible()

            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
