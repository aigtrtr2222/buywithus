"""🥚 이스터에그(바구니 합치기) + 푸터 인스타 링크를 실제 Chrome으로 확인.

사용: .venv/Scripts/python tests/egg_check.py
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
INSTA = "https://www.instagram.com/buywithus12/"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)],
        cwd=ROOT, env={**os.environ, "BWU_DATA_DIR": tempfile.mkdtemp(prefix="bwu-egg-")},
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

            def page_with_random(value, **ctx_kw):
                ctx = browser.new_context(**ctx_kw)
                ctx.on("weberror", lambda e: errors.append(str(e.error)))
                if value is not None:
                    ctx.add_init_script(f"Math.random = () => {value};")
                return ctx.new_page()

            # 1) 운 나쁨(50%): 바구니 열어도 게임 없음, 게임 스크립트도 안 불러옴
            p = page_with_random(0.5)
            p.goto(base)
            p.hover("#basket")
            expect(p.locator("#intro")).to_have_count(0, timeout=5000)
            p.wait_for_timeout(500)
            assert p.locator("#eggDialog").count() == 0
            assert not p.evaluate("!!window.Matter"), "게임 안 뜰 때는 엔진도 안 불러와야 함"

            # 2) 건너뛰기는 확률이 5%여도 게임 없음 (바구니를 직접 열 때만)
            p = page_with_random(0.05)
            p.goto(base)
            p.click("#introSkip")
            p.wait_for_timeout(1500)
            assert p.locator("#eggDialog").count() == 0

            # 3) 운 좋음(5% < 10%): 바구니 클릭 → 이스터에그
            p = page_with_random(0.05, viewport={"width": 1280, "height": 900})
            p.goto(base)
            p.click("#basket")
            dlg = p.locator("#eggDialog")
            expect(dlg).to_be_visible(timeout=6000)
            expect(dlg).to_contain_text("EASTER EGG")
            expect(dlg).to_contain_text("10% 확률")
            expect(dlg.locator(".egg__ladder li")).to_have_count(11)
            # Math.random 고정 → 항상 같은 블루베리 → 같은 자리에 떨어뜨리면 합쳐져야 함
            canvas = dlg.locator("canvas")
            box = canvas.bounding_box()
            for _ in range(6):
                canvas.click(position={"x": box["width"] / 2, "y": 40})
                p.wait_for_timeout(520)
            expect(dlg.locator("#eggScore")).not_to_have_text("0", timeout=5000)
            p.wait_for_timeout(800)
            p.screenshot(path=str(OUT / "bwu_egg_desktop.png"))
            # 큰 과일을 쏟아부어 바구니가 넘치면 게임 오버 → 다시 하기
            p.evaluate("window.BWUEgg._fill()")
            try:
                expect(dlg.locator(".egg__over")).to_be_visible(timeout=20000)
            except AssertionError:
                p.screenshot(path=str(OUT / "bwu_egg_FAIL.png"))
                raise
            best = int(dlg.locator("#eggBest").inner_text())
            assert best > 0
            dlg.locator(".egg__over [data-egg-restart]").click()
            expect(dlg.locator("#eggScore")).to_have_text("0")
            expect(dlg.locator(".egg__over")).to_be_hidden()
            dlg.locator(".egg__actions [data-egg-close]").click()
            expect(dlg).to_be_hidden()

            # 4) 주소에 ?egg → 항상, 모바일 터치도 동작 + 가로 넘침 없음
            p = page_with_random(None, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            p.goto(base + "/?egg")
            p.tap("#basket")
            dlg = p.locator("#eggDialog")
            expect(dlg).to_be_visible(timeout=6000)
            box = dlg.locator("canvas").bounding_box()
            assert box["height"] / box["width"] > 1.45, "캔버스 비율이 찌그러짐"
            assert box["y"] + box["height"] <= 844, "모바일에서 게임판이 화면 밖으로 나감"
            dlg.locator("canvas").tap(position={"x": 60, "y": 40})
            p.wait_for_timeout(1200)
            assert not p.evaluate("document.documentElement.scrollWidth > innerWidth")
            p.screenshot(path=str(OUT / "bwu_egg_mobile.png"))

            # 5) 푸터: 큰 로고 = 인스타 링크, QR
            p = page_with_random(0.5, viewport={"width": 1280, "height": 900})
            p.goto(base)
            p.click("#introSkip")
            p.wait_for_timeout(1500)   # 인트로 → 본문 등장 애니메이션(축소→원래 크기) 끝날 때까지
            logo = p.locator(".footer__logo")
            expect(logo).to_have_attribute("href", INSTA)
            expect(logo).to_have_attribute("target", "_blank")
            assert logo.locator("img").bounding_box()["width"] >= 80
            expect(p.locator(".footer__qr img")).to_be_visible()
            assert p.evaluate("document.querySelector('.footer__qr img').naturalWidth") > 0
            p.locator(".footer").scroll_into_view_if_needed()
            p.wait_for_timeout(600)
            p.screenshot(path=str(OUT / "bwu_footer.png"))
            browser.close()
        assert not errors, errors
        print("EGG CHECK PASSED; screenshots in", OUT)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
