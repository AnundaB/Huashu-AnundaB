from pathlib import Path
import re
import asyncio
from playwright.async_api import async_playwright

URL = "https://x.com/0xwhrrari/status/2061924184196788734/video/1"
OUT_DIR = Path.home() / ".agents/skills/huashu-md-html/outputs/x"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT = OUT_DIR / "x-post-2061924184196788734-clean.md"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        context = await browser.new_context(
            viewport={"width": 1200, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        print()
        print("Browser opened.")
        print("1) ถ้า X ให้ login ให้ login ก่อน")
        print("2) รอให้โพสต์/วิดีโอจริงแสดงบนหน้าจอ")
        print("3) กลับมาที่ Terminal แล้วกด Enter")
        print()
        input("Press Enter after the X post is visible... ")

        articles = page.locator("article")
        count = await articles.count()

        if count == 0:
            raise RuntimeError("No article found. The post may not be visible or login is required.")

        text = await articles.first.inner_text(timeout=30000)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Clean common X UI noise, but keep post text / author / metrics if present
        lines = []
        seen = set()

        drop_exact = {
            "Post",
            "Reply",
            "Repost",
            "Like",
            "View",
            "Views",
            "Share",
            "Bookmark",
            "More",
        }

        for raw in text.splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue
            if line in drop_exact:
                continue

            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)

        md = "# X Post: 2061924184196788734\n\n"
        md += f"Source: {URL}\n\n"
        md += "## Captured Text\n\n"

        for line in lines:
            md += f"{line}\n\n"

        md += "\n---\n\n"
        md += "Note: This captures visible text from the X post. It does not download the video file.\n"

        OUT.write_text(md, encoding="utf-8")
        print(f"\nSaved: {OUT}")

        await browser.close()

asyncio.run(main())
