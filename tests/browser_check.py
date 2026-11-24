"""실제 Chrome으로 글쓰기 → 참여 → 공구 수다방 대화 → 취소/삭제 흐름 확인 (임시 DB).

사용: .venv/Scripts/python tests/browser_check.py   (pip install playwright, 설치된 Chrome 사용)
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("BWU_SHOT_DIR", tempfile.gettempdir()))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_post(page, title, kakao=""):
    page.locator("[data-open-write]").first.click()
    f = page.locator("#writeForm")
    f.locator("[name=title]").fill(title)
    f.locator("[name=leader]").fill("자취 3년차")
    f.locator("[name=item]").fill("양파 3kg 한 망")
    f.locator("[name=price]").fill("6900")
    f.locator("[name=place]").fill("화양동 OO마트 앞")
    f.locator("[name=area]").fill("화양동")
    f.locator("[name=kakao]").fill(kakao)
    f.locator("[type=submit]").click()


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    data = tempfile.mkdtemp(prefix="bwu-test-")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
        cwd=ROOT, env={**os.environ, "BWU_DATA_DIR": data},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    errors = []
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/api/health"); break
            except OSError:
                time.sleep(0.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            leader = browser.new_context(viewport={"width": 1280, "height": 900})
            guest = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            outsider = browser.new_context(viewport={"width": 1280, "height": 900})
            for ctx in (leader, guest, outsider):
                ctx.on("weberror", lambda e: errors.append(str(e.error)))

            # --- 리더: 글쓰기 (오픈카톡 형식 틀리면 거부, 비워두면 통과)
            a = leader.new_page()
            a.goto(base)
            a.click("#introSkip")
            expect(a.locator("#empty")).to_be_visible()
            expect(a.locator("#chat")).to_be_hidden()          # 참여한 공구 없으면 봉투 없음
            write_post(a, "양파 한 망 셋이 나눠요", kakao="https://evil.example/x")
            expect(a.locator("#formError")).to_contain_text("open.kakao.com")
            a.locator("#writeForm [name=kakao]").fill("")
            a.locator("#writeForm [type=submit]").click()
            card = a.locator(".card").first
            expect(card).to_contain_text("내 모집글")
            expect(card).to_contain_text("1 / 3명")
            expect(a.locator("#chatFab")).to_be_visible()

            # --- 손님(모바일): 참여 → 수다방 열기 → 인사
            b = guest.new_page()
            b.goto(base)
            b.click("#introSkip")
            expect(b.locator("#chat")).to_be_hidden()
            gcard = b.locator(".card").first
            expect(gcard).to_contain_text("2,300")
            gcard.locator("[data-join]").click()
            b.check("#noShowCheck")
            b.click("#joinBtn")
            expect(b.locator("#openRoomBtn")).to_be_visible()
            expect(b.locator("#kakaoLink")).to_be_hidden()      # 오픈카톡 없는 글
            b.click("#openRoomBtn")
            expect(b.locator("#chatBag")).to_be_visible()
            expect(b.locator("#chatTitle")).to_have_text("양파 한 망 셋이 나눠요")
            expect(b.locator("#chatSub")).to_contain_text("나는")
            expect(b.locator("#chatMembers li")).to_have_count(2)
            expect(b.locator(".msg-sys").first).to_contain_text("리더")
            b.fill("#chatInput", "저도 양파 필요해요 <b>!</b>")
            b.click(".chat__send")
            expect(b.locator(".msg.is-mine")).to_contain_text("<b>!</b>")
            assert not b.evaluate("document.documentElement.scrollWidth > innerWidth"), "모바일 가로 넘침"
            b.screenshot(path=str(OUT / "bwu_room_mobile.png"))

            # --- 리더: 배지 → 방이 하나라 바로 입장 → 답장
            expect(a.locator("#chatBadge")).to_have_text("1", timeout=20000)
            a.click("#chatFab")
            expect(a.locator("#chatTitle")).to_have_text("양파 한 망 셋이 나눠요")
            expect(a.locator(".msg:not(.is-mine)")).to_contain_text("저도 양파 필요해요")
            expect(a.locator(".msg-sys")).to_have_count(2)      # 개설 + 입장 안내
            a.fill("#chatInput", "내일 7시에 마트 앞에서 봬요")
            a.press("#chatInput", "Enter")
            expect(a.locator(".msg.is-mine .msg__bubble")).to_have_text("내일 7시에 마트 앞에서 봬요")
            expect(b.locator(".msg:not(.is-mine)")).to_contain_text("내일 7시에", timeout=10000)
            expect(b.locator(".msg:not(.is-mine) .msg__crown")).to_be_visible()   # 리더 표시

            # --- 리더가 두 번째 글 → 목록에서 방 고르기
            a.click("#chatClose")
            write_post(a, "계란 한 판 나눠요")
            expect(a.locator(".card")).to_have_count(2)
            a.wait_for_timeout(1500)
            expect(a.locator("#chatBadge")).to_be_hidden()      # 내가 연 방은 새 메시지 아님
            a.click("#chatFab")
            expect(a.locator(".room__dot")).to_have_count(0)
            expect(a.locator(".room")).to_have_count(2)
            a.wait_for_timeout(400)
            a.screenshot(path=str(OUT / "bwu_rooms_desktop.png"))
            a.locator(".room", has_text="계란 한 판").click()
            expect(a.locator("#chatMembers li")).to_have_count(1)
            a.click("#chatBack")
            expect(a.locator(".room")).to_have_count(2)
            a.locator(".room", has_text="양파 한 망").click()
            expect(a.locator(".msg")).to_have_count(2)
            a.wait_for_timeout(400)
            a.screenshot(path=str(OUT / "bwu_room_desktop.png"))
            a.keyboard.press("Escape")
            expect(a.locator("#chatBag")).to_be_hidden()

            # --- 참여 안 한 사람: 수다방 없음, API도 거부
            c = outsider.new_page()
            c.goto(base)
            c.click("#introSkip")
            expect(c.locator(".card")).to_have_count(2)
            expect(c.locator("#chat")).to_be_hidden()
            status = c.evaluate("""async () => (await fetch('/api/posts/1/chat', {headers: {'X-BWU-Token': 'x'.repeat(40)}})).status""")
            assert status == 403, status

            # --- 손님 참여 취소 → 수다방 사라짐
            b.click("#chatClose")
            b.locator(".card [data-join]").first.click()
            b.click("#leaveBtn")
            expect(b.locator("#chat")).to_be_hidden()

            # --- 리더 삭제
            a.locator(".card", has_text="양파 한 망").locator("[data-join]").click()
            expect(a.locator("#leaveBtn")).to_have_text("모집글 삭제")
            a.once("dialog", lambda d: d.accept())
            a.click("#leaveBtn")
            expect(a.locator(".card")).to_have_count(1)
            a.click("#chatFab")
            expect(a.locator("#chatTitle")).to_have_text("계란 한 판 나눠요")  # 남은 방 하나 → 바로 입장
            browser.close()
        assert not errors, errors
        print("BROWSER CHECK PASSED; screenshots in", OUT)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
