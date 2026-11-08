"""只读抓取运单数据页「运单生成时间」口径的查询协议；不提交任何导出任务。"""
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fengshen_bill import PROJECT_ROOT, WAYBILL_URL, atomic_json


def main(start, end):
    from playwright.sync_api import sync_playwright
    from fengshen_auth import SessionVault
    state = SessionVault().load()
    if state is None:
        raise SystemExit("请先在薪酬系统完成风神登录")
    run = PROJECT_ROOT / "outputs" / "fengshen_waybill_inspection" / uuid.uuid4().hex
    run.mkdir(parents=True)
    captured = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=False)
        try:
            context = browser.new_context(storage_state=state, accept_downloads=True)
            state = None
            page = context.new_page()

            def on_request(request):
                if "httpizza.ele.me" in request.url and request.method == "POST":
                    try:
                        body = request.post_data_json
                    except Exception:
                        body = None
                    captured.append({"url": request.url.split("?")[0], "body": body})

            page.on("request", on_request)
            page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            frame = page.frame_locator("iframe[name='sirong-app']")
            tour = frame.locator("button.ant-tour-close:visible")
            if tour.count() == 1:
                tour.click()
            expand = frame.get_by_text("展开筛选", exact=True)
            if expand.count() == 1 and expand.is_visible():
                expand.click()
            page.wait_for_timeout(500)
            notes = {}
            dropdown = frame.locator(".ant-space-compact:has(input[placeholder='开始日期']) .ant-select-selector")
            if dropdown.count() == 1:
                dropdown.click()
                page.wait_for_timeout(500)
                options = frame.locator(".ant-select-dropdown:visible .ant-select-item-option-content").all_text_contents()
                notes["date_options"] = options
                atomic_json(run / "date_options.json", {"options": options})
                choice = frame.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
                    has_text=re.compile(r"^运单生成时间$"))
                if choice.count() >= 1:
                    choice.first.click()
                    notes["selected"] = "运单生成时间"
                else:
                    notes["selected"] = None
            else:
                notes["date_options"] = "no-compact-select"
            for placeholder, value in (("开始日期", start), ("结束日期", end)):
                control = frame.get_by_placeholder(placeholder, exact=True)
                if control.count() >= 1:
                    control.first.fill(value)
                    control.first.press("Enter")
            page.wait_for_timeout(500)
            mark = len(captured)
            query = frame.get_by_role("button", name=re.compile(r"^查\s*询$"))
            query.first.click()
            page.wait_for_timeout(4000)
            page.screenshot(path=str(run / "page.png"))
            atomic_json(run / "capture.json", {"start": start, "end": end, **notes,
                                               "requests_around_query": captured[mark:],
                                               "all_requests": captured})
            print(f"capture saved: {run}")
            print("date_options:", notes.get("date_options"))
        finally:
            browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
