from pathlib import Path
import asyncio
import re
from playwright.async_api import async_playwright

URL = "https://chatgpt.com/share/6a23c4f7-f198-83ec-86bd-ef44372f3dc7"

OUT_DIR = Path.home() / "huashu-md-html/outputs/chatgpt"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT = OUT_DIR / "chatgpt-share-6a23c4f7-clean.md"

def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return line

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        context = await browser.new_context(
            viewport={"width": 1300, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)

        print()
        print("Browser opened.")
        print("1) รอให้หน้า ChatGPT share โหลดเสร็จ")
        print("2) ถ้ามี Cloudflare / login / continue ให้กดผ่านก่อน")
        print("3) เลื่อนดูให้ข้อความแชทขึ้นครบ")
        print("4) กลับมาที่ Terminal แล้วกด Enter")
        print()
        input("Press Enter after the shared chat is visible... ")

        await page.wait_for_timeout(2000)

        title = await page.title()
        body_text = await page.locator("body").inner_text(timeout=30000)

        raw_lines = body_text.splitlines()
        lines = []
        seen_noise = set()

        drop_exact = {
            "ChatGPT",
            "Log in",
            "Sign up",
            "Get started",
            "Try ChatGPT",
            "Download",
            "Share",
            "Copy link",
            "Open sidebar",
            "Close sidebar",
            "New chat",
        }

        drop_contains = [
            "ChatGPT can make mistakes",
            "Check important info",
            "By messaging ChatGPT",
            "Terms",
            "Privacy Policy",
        ]

        for raw in raw_lines:
            line = clean_line(raw)

            if not line:
                continue
            if line in drop_exact:
                continue
            if any(x.lower() in line.lower() for x in drop_contains):
                continue

            # กันเมนูซ้ำ ๆ แต่ไม่ลบเนื้อหาแชท
            key = line.lower()
            if len(line) < 40 and key in seen_noise:
                continue
            seen_noise.add(key)

            lines.append(line)

        # ทำ markdown แบบอ่านง่าย
        md = "# ChatGPT Shared Conversation\n\n"
        md += f"Source: {URL}\n\n"
        md += f"Page title: {title}\n\n"
        md += "---\n\n"

        # ถ้าเจอคำบอก role ให้พยายามแยก section
        current_block = []

        for line in lines:
            if line in {"You said:", "ChatGPT said:"}:
                if current_block:
                    md += "\n".join(current_block).strip() + "\n\n"
                    current_block = []
                md += f"## {line.replace(':', '')}\n\n"
                continue

            current_block.append(line)

        if current_block:
            md += "\n".join(current_block).strip() + "\n"

        md = re.sub(r"\n{4,}", "\n\n\n", md).strip() + "\n"

        OUT.write_text(md, encoding="utf-8")
        print(f"\nSaved: {OUT}")

        await browser.close()

asyncio.run(main())
