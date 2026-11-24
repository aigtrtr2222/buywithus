"""실제 Chrome으로 글쓰기 → 다른 사람 참여 → 링크 공개 → 취소/삭제 흐름 확인 (임시 DB).

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
            for ctx in (leader, guest):
                ctx.on("weberror", lambda e: errors.append(str(e.error)))

            a = leader.new_page()
            a.goto(base)
            a.click("#introSkip")
            expect(a.locator("#empty")).to_be_visible()
            a.locator("[data-open-write]").first.click()
            f = a.locator("#writeForm")
            f.locator("[name=title]").fill("양파 한 망 셋이 나눠요")
            f.locator("[name=leader]").fill("자취 3년차")
            f.locator("[name=item]").fill("양파 3kg 한 망")
            f.locator("[name=price]").fill("6900")
            f.locator("[name=place]").fill("화양동 OO마트 앞")
            f.locator("[name=area]").fill("화양동")
            f.locator("[name=kakao]").fill("https://evil.example/x")
            f.locator("[type=submit]").click()
            expect(a.locator("#formError")).to_contain_text("오픈카카오톡")
            f.locator("[name=kakao]").fill("https://open.kakao.com/o/testroom")
            f.locator("[type=submit]").click()
            card = a.locator(".card").first
            expect(card).to_contain_text("양파 한 망 셋이 나눠요")
            expect(card).to_contain_text("내 모집글")
            expect(card).to_contain_text("1 / 3명")

            b = guest.new_page()
            b.goto(base)
            b.click("#introSkip")
            gcard = b.locator(".card").first
            expect(gcard).to_contain_text("자취 3년차")
            expect(gcard).to_contain_text("2,300")
            gcard.locator("[data-join]").click()
            expect(b.locator("#joinBtn")).to_be_disabled()
            b.check("#noShowCheck")
            b.click("#joinBtn")
            expect(b.locator("#kakaoLink")).to_have_attribute("href", "https://open.kakao.com/o/testroom")
            b.screenshot(path=str(OUT / "bwu_mobile_joined.png"))
            b.keyboard.press("Escape")
            expect(gcard).to_contain_text("2 / 3명")

            # 새로고침해도 참여 상태 유지 (DB + 브라우저 토큰)
            b.reload(); b.click("#introSkip")
            expect(b.locator(".card").first).to_contain_text("오픈채팅")

            # 리더 화면도 새로고침 시 2명 반영
            a.reload(); a.click("#introSkip")
            expect(a.locator(".card").first).to_contain_text("2 / 3명")
            a.screenshot(path=str(OUT / "bwu_desktop.png"), full_page=False)

            # 참여 취소
            b.locator(".card [data-join]").first.click()
            b.click("#leaveBtn")
            expect(b.locator(".card").first).to_contain_text("1 / 3명")
            wide = b.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not wide, "모바일 가로 넘침"

            # 리더 삭제
            a.locator(".card [data-join]").first.click()
            expect(a.locator("#leaveBtn")).to_have_text("모집글 삭제")
            a.once("dialog", lambda d: d.accept())
            a.click("#leaveBtn")
            expect(a.locator("#empty")).to_be_visible()
            browser.close()
        assert not errors, errors
        print("BROWSER CHECK PASSED; screenshots in", OUT)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
