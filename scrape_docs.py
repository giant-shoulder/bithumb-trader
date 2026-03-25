"""
빗썸 API 문서 전체 스크래핑 → PDF
ReadMe.io SPA: 사이드바 클릭 탐색 방식
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "https://apidocs.bithumb.com"
OUTPUT_PDF = "bithumb_api_docs.pdf"


async def expand_all_sidebar(page):
    """사이드바 모든 섹션 펼치기"""
    for _ in range(5):
        expanded = await page.evaluate("""
            () => {
                let count = 0;
                // ReadMe.io 사이드바 토글 버튼들
                const toggles = document.querySelectorAll(
                    '[class*="CategoryToggle"], [class*="toggle"], [aria-expanded="false"],' +
                    'button[class*="sidebar"], [class*="accordion"] button'
                );
                toggles.forEach(btn => {
                    const expanded = btn.getAttribute('aria-expanded');
                    if (expanded === 'false' || expanded === null) {
                        btn.click();
                        count++;
                    }
                });
                return count;
            }
        """)
        if expanded == 0:
            break
        await page.wait_for_timeout(800)


async def collect_sidebar_links(page, base_url):
    """사이드바에서 모든 문서 페이지 링크 수집"""
    await page.goto(base_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)
    await expand_all_sidebar(page)
    await page.wait_for_timeout(1000)

    links = await page.evaluate("""
        (origin) => {
            const results = new Map();
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href.split('#')[0];
                const text = a.textContent.trim();
                if (
                    href.startsWith(origin) &&
                    href !== origin &&
                    href !== origin + '/' &&
                    text.length > 0 &&
                    text.length < 100
                ) {
                    results.set(href, text);
                }
            });
            return [...results.entries()].map(([href, text]) => ({ href, text }));
        }
    """, BASE_URL)

    return links


async def get_page_content(page, url):
    """페이지 콘텐츠 HTML 추출"""
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2500)

        title = await page.title()

        content = await page.evaluate("""
            () => {
                // ReadMe.io 콘텐츠 선택자
                const selectors = [
                    '.rm-Article', '.markdown-body', 'article',
                    '[class*="content-body"]', '[class*="PageContent"]',
                    'main [class*="content"]', '#content', 'main'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = el.textContent.trim();
                        if (text.length > 50) {
                            // 불필요한 interactive 요소 제거
                            el.querySelectorAll('script, style, [class*="Feedback"], [class*="suggest"]').forEach(e => e.remove());
                            return { html: el.outerHTML, found: sel };
                        }
                    }
                }
                // fallback: body 전체에서 nav/sidebar 제거 후
                const body = document.body.cloneNode(true);
                body.querySelectorAll('nav, header, footer, aside, [class*="sidebar"], [class*="navbar"]').forEach(e => e.remove());
                return { html: body.innerHTML, found: 'body' };
            }
        """)

        print(f"  ✓ [{content['found']}] {title}")
        return title, content['html']

    except Exception as e:
        print(f"  ✗ {url}: {e}")
        return None, None


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        print("=== 1단계: 사이드바 링크 수집 ===")

        # 각 주요 섹션에서 링크 수집
        all_links = {}
        sections = [
            BASE_URL,
            BASE_URL + "/docs",
            BASE_URL + "/reference",
        ]

        for section_url in sections:
            links = await collect_sidebar_links(page, section_url)
            for l in links:
                if l['href'] not in all_links:
                    all_links[l['href']] = l['text']
            print(f"  {section_url}: {len(links)}개")

        print(f"\n총 {len(all_links)}개 페이지 발견")

        print("\n=== 2단계: 각 페이지 스크래핑 ===")

        page_sections = []
        visited = set()

        # 메인 페이지들 먼저
        for url in sections:
            if url not in visited:
                visited.add(url)
                title, html = await get_page_content(page, url)
                if html:
                    page_sections.append((title or url, html))

        # 사이드바 링크들
        for url, text in all_links.items():
            if url in visited:
                continue
            visited.add(url)
            title, html = await get_page_content(page, url)
            if html:
                page_sections.append((title or text, html))

        print(f"\n=== 3단계: PDF 생성 ({len(page_sections)}페이지) ===")

        # TOC 생성
        toc_items = "\n".join(
            f'<li>{i+1}. {title}</li>'
            for i, (title, _) in enumerate(page_sections)
        )

        # 본문 HTML
        body_sections = "\n".join(
            f'''<div class="page-section">
  <div class="section-header">
    <span class="section-num">{i+1}</span> {title}
  </div>
  {html}
</div>
<div class="page-break"></div>'''
            for i, (title, html) in enumerate(page_sections)
        )

        full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  @page {{ margin: 12mm 15mm; }}
  body {{
    font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    font-size: 13px; color: #222; line-height: 1.65; margin: 0; padding: 0;
  }}
  .cover {{
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 100vh; page-break-after: always;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white; text-align: center;
  }}
  .cover h1 {{ font-size: 36px; margin-bottom: 10px; }}
  .cover p {{ font-size: 16px; opacity: 0.7; }}
  .toc {{ padding: 20px 0; page-break-after: always; }}
  .toc h2 {{ font-size: 20px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
  .toc ol {{ column-count: 2; font-size: 12px; line-height: 1.8; }}
  .page-section {{ margin-bottom: 10px; }}
  .section-header {{
    background: #f0f4f8; padding: 8px 12px;
    font-size: 14px; font-weight: bold;
    border-left: 4px solid #3182ce; margin-bottom: 16px;
  }}
  .section-num {{ color: #3182ce; margin-right: 8px; }}
  .page-break {{ page-break-after: always; height: 1px; }}
  pre, code {{
    background: #f6f8fa; font-family: 'Courier New', monospace;
    font-size: 11.5px; border-radius: 3px;
  }}
  code {{ padding: 1px 5px; }}
  pre {{ padding: 12px; overflow-x: auto; white-space: pre-wrap;
        border: 1px solid #e1e4e8; margin: 8px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }}
  th, td {{ border: 1px solid #ddd; padding: 5px 9px; vertical-align: top; }}
  th {{ background: #f0f4f8; font-weight: 600; }}
  h1 {{ font-size: 20px; color: #1a1a2e; margin: 20px 0 10px; }}
  h2 {{ font-size: 17px; color: #2d3748; margin: 16px 0 8px; }}
  h3 {{ font-size: 14px; color: #4a5568; }}
  a {{ color: #3182ce; }}
  img {{ max-width: 100%; }}
  .rm-Callout, [class*="callout"] {{
    border-left: 3px solid #3182ce; padding: 8px 12px;
    background: #ebf8ff; margin: 8px 0;
  }}
</style>
</head>
<body>

<div class="cover">
  <h1>빗썸 API 레퍼런스</h1>
  <p>apidocs.bithumb.com</p>
</div>

<div class="toc">
  <h2>목차</h2>
  <ol>{toc_items}</ol>
</div>

{body_sections}
</body>
</html>"""

        await page.set_content(full_html, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.pdf(
            path=OUTPUT_PDF,
            format="A4",
            print_background=True,
        )

        await browser.close()
        size = Path(OUTPUT_PDF).stat().st_size / 1024 / 1024
        print(f"완료: {OUTPUT_PDF} ({size:.1f} MB)")


if __name__ == "__main__":
    asyncio.run(main())
