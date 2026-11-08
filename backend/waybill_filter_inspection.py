"""只读抓取运单数据页「运单终态时间 + 标品筛选」的查询协议；不提交任何导出任务。"""
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fengshen_bill import PROJECT_ROOT, WAYBILL_URL, atomic_json


def dump_filters(frame):
    notes = {"filter_labels": [], "visible_options": []}
    try:
        for label in frame.locator(".ant-form-item-label label").all_text_contents():
            text = label.strip()
            if text:
                notes["filter_labels"].append(text)
    except Exception as error:
        notes["filter_labels"] = f"label dump failed: {error}"
    return notes


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
            page = context.new_page()

            def on_request(request):
                if "httpizza.ele.me" in request.url and request.method == "POST":
                    try:
                        body = request.post_data_json
                    except Exception:
                        body = None
                    captured.append({"url": request.url.split("?")[0], "body": body})

            responses = {}

            def on_response(response):
                if "queryEnumerate" in response.url:
                    try:
                        responses["queryEnumerate"] = response.json()
                    except Exception as error:
                        responses["queryEnumerate"] = f"unreadable: {error}"

            page.on("request", on_request)
            page.on("response", on_response)
            page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(9000)
            page.screenshot(path=str(run / "page_loaded.png"))
            notes = {"page_url": page.url, "page_title": page.title(),
                     "frames": [{"name": item.name, "url": item.url[:140]} for item in page.frames]}
            buttons = {}
            for item in page.frames:
                try:
                    texts = [text.strip() for text in item.locator("button").all_text_contents()
                             if text.strip()][:25]
                except Exception:
                    texts = "unavailable"
                buttons[item.name or item.url[:80]] = texts
            notes["buttons_by_frame"] = buttons
            frame = None
            for item in page.frames:
                try:
                    if item.locator("button").filter(has_text=re.compile(r"查\s*询")).count() >= 1:
                        frame = item
                        break
                except Exception:
                    continue
            if frame is None and "51388" in page.url:
                # SSO 握手会丢掉 hash 落到默认工作台，认证完成后再次直达运单页。
                page.goto(WAYBILL_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(9000)
                notes["page_url"] = page.url
                for item in page.frames:
                    try:
                        if item.locator("button").filter(has_text=re.compile(r"查\s*询")).count() >= 1:
                            frame = item
                            break
                    except Exception:
                        continue
            if frame is None:
                atomic_json(run / "capture.json", {"start": start, "end": end, **notes,
                                                   "all_requests": captured})
                print(f"capture saved (no query button): {run}")
                print("page_url:", notes["page_url"])
                for key, texts in buttons.items():
                    print("frame:", key, "| buttons:", texts)
                return
            notes["query_frame"] = frame.name or frame.url[:120]
            tour = frame.locator("button.ant-tour-close:visible")
            if tour.count() == 1:
                tour.click()
            expand = frame.get_by_text("展开筛选", exact=True)
            if expand.count() == 1 and expand.is_visible():
                expand.click()
            page.wait_for_timeout(800)
            notes.update(dump_filters(frame))
            page.screenshot(path=str(run / "page_loaded.png"))
            query = frame.locator("button").filter(has_text=re.compile(r"查\s*询"))
            if query.count() == 0:
                notes["query_button"] = "not found"
                atomic_json(run / "capture.json", {"start": start, "end": end, **notes,
                                                   "all_requests": captured})
                print(f"capture saved (no query button): {run}")
                print("filter_labels:", notes.get("filter_labels"))
                return
            notes["query_button"] = f"found {query.count()}"

            dropdown = frame.locator(".ant-space-compact:has(input[placeholder='开始日期']) .ant-select-selector")
            if dropdown.count() == 1:
                dropdown.click()
                page.wait_for_timeout(500)
                choice = frame.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
                    has_text=re.compile(r"^运单终态时间$"))
                if choice.count() >= 1:
                    choice.first.click()
                    notes["selected"] = "运单终态时间"
                else:
                    notes["selected"] = None
            for placeholder, value in (("开始日期", start), ("结束日期", end)):
                control = frame.get_by_placeholder(placeholder, exact=True)
                if control.count() >= 1:
                    control.first.fill(value)
                    control.first.press("Enter")
            page.wait_for_timeout(500)
            mark = len(captured)
            query.first.click()
            page.wait_for_timeout(4000)
            notes["finish_basis_query"] = captured[mark:]
            page.screenshot(path=str(run / "finish_basis.png"))

            # 深度探测「标品」表单项：转储结构，并尝试各类控件打开后抓取选项。
            probe = {"biaopin_html": None, "biaopin_dropdowns": [], "biaopin_options": [],
                     "all_city_send_clicked": None}
            form_item = frame.locator(".ant-form-item").filter(has=frame.locator(
                ".ant-form-item-label label", has_text=re.compile(r"标品")))
            if form_item.count() >= 1:
                probe["biaopin_html"] = form_item.first.inner_html()[:2500]
                controls = [form_item.first.locator(".ant-select-selector"),
                            form_item.first.locator(".ant-select")]
                for index, control in enumerate(controls):
                    if probe["all_city_send_clicked"] is not None:
                        break
                    try:
                        if control.count() == 0 or not control.first.is_visible():
                            continue
                        control.first.click()
                        page.wait_for_timeout(900)
                        dropdown = frame.locator(".ant-select-dropdown:visible")
                        visible = [text.strip() for text in dropdown.first.locator(
                            ".ant-select-item-option-content").all_text_contents()]
                        probe["biaopin_dropdowns"].append({f"control#{index}-visible": visible})
                        # 选项列表为虚拟滚动：用方向键逐项下移，直到「全城送」成为活动项。
                        active = dropdown.first.locator(".ant-select-item-option-active .ant-select-item-option-content")
                        for _ in range(50):
                            if active.count() >= 1 and "全城送" in (active.first.text_content() or ""):
                                break
                            page.keyboard.press("ArrowDown")
                            page.wait_for_timeout(120)
                        if active.count() >= 1 and "全城送" in (active.first.text_content() or ""):
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(600)
                            tags = [text.strip() for text in form_item.first.locator(
                                ".ant-select-selection-item-content").all_text_contents()]
                            probe["biaopin_selected_tags"] = tags
                            if "全城送" in tags:
                                probe["all_city_send_clicked"] = f"control#{index}-keyboard"
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(300)
                                break
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(250)
                    except Exception as error:
                        probe["biaopin_dropdowns"].append({f"control#{index}": f"error: {error}"})
            else:
                probe["biaopin_html"] = "form item not found"
            notes.update(probe)
            if probe["all_city_send_clicked"] is not None:
                page.wait_for_timeout(500)
                mark = len(captured)
                query.first.click()
                page.wait_for_timeout(4000)
                notes["all_city_send_query"] = captured[mark:]
                page.screenshot(path=str(run / "all_city_send.png"))
            atomic_json(run / "capture.json", {"start": start, "end": end, "query_enumerate": responses.get("queryEnumerate"),
                                               **notes, "all_requests": captured})
            print(f"capture saved: {run}")
            print("selected:", notes.get("selected"), "| all_city_send_clicked:", probe["all_city_send_clicked"])
            print("filter_labels:", notes.get("filter_labels"))
        finally:
            browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
