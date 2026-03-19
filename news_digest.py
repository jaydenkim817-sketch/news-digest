import os
import re
import smtplib
import feedparser
import anthropic
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y년 %m월 %d일")
TODAY_FILE = datetime.now(KST).strftime("%Y-%m-%d")

RSS_FEEDS = [
    {"url": "https://feeds.feedburner.com/TechCrunch", "category": "IT/테크", "source": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "category": "IT/테크", "source": "The Verge"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "category": "경제/금융", "source": "Bloomberg"},
    {"url": "https://www.hankyung.com/feed/all-news", "category": "경제/금융", "source": "한국경제"},
    {"url": "https://www.mk.co.kr/rss/40300001/", "category": "경제/금융", "source": "매일경제"},
]


def fetch_news():
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= 4:
                    break
                title = entry.get("title", "").strip()[:80]
                if not title:
                    continue
                articles.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "source": feed_info["source"],
                    "category": feed_info["category"],
                })
                count += 1
            print(f"  {feed_info['source']}: {count}건")
        except Exception as e:
            print(f"  {feed_info['source']} 실패: {e}")
    print(f"총 {len(articles)}건 수집")
    return articles[:15]


def analyze_with_claude(articles):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    lines = "\n".join([f"{i+1}. {a['title']}" for i, a in enumerate(articles)])

    prompt = f"""아래 뉴스 중 주식시장(반도체/코스피/금리/AI/환율) 관련 뉴스 5개를 골라주세요.
각 뉴스마다 다음 형식으로 정확히 작성하세요:

번호: [원본 번호]
요약: [한 줄 요약]
신호: [호재 또는 악재 또는 중립]
근거: [한 줄 근거]

---

{lines}"""

    print("Claude 분석 중...")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    print("Claude 응답 수신 완료")

    # 텍스트 파싱 (JSON 사용 안 함)
    results = []
    blocks = re.split(r'\n(?=번호:)', raw)
    for block in blocks:
        try:
            num_m = re.search(r'번호:\s*(\d+)', block)
            sum_m = re.search(r'요약:\s*(.+)', block)
            sig_m = re.search(r'신호:\s*(호재|악재|중립)', block)
            rea_m = re.search(r'근거:\s*(.+)', block)

            if not (num_m and sum_m and sig_m):
                continue

            idx = int(num_m.group(1)) - 1
            if 0 <= idx < len(articles):
                article = articles[idx].copy()
                article["ai_summary"] = sum_m.group(1).strip()
                article["signal"] = sig_m.group(1).strip()
                article["reason"] = rea_m.group(1).strip() if rea_m else ""
                results.append(article)
        except Exception:
            continue

    print(f"분석 완료: {len(results)}건")
    return results if results else articles[:3]


SIGNAL_STYLE = {
    "호재": ("#3B6D11", "#EAF3DE"),
    "악재": ("#A32D2D", "#FCEBEB"),
    "중립": ("#5F5E5A", "#F1EFE8"),
}


def build_html(articles):
    counts = {"호재": 0, "악재": 0, "중립": 0}
    for a in articles:
        sig = a.get("signal", "중립")
        if sig in counts:
            counts[sig] += 1

    cards = ""
    for a in articles:
        sig = a.get("signal", "중립")
        tc, bg = SIGNAL_STYLE.get(sig, SIGNAL_STYLE["중립"])
        cards += f"""
<div style="border:1px solid #e5e5e5;border-radius:12px;padding:16px;margin-bottom:12px;background:#fff;">
  <div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:8px;">
    <a href="{a['link']}" style="font-size:14px;font-weight:600;color:#111;text-decoration:none;flex:1;line-height:1.5;">{a['title']}</a>
    <span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap;color:{tc};background:{bg};">{sig}</span>
  </div>
  <div style="font-size:13px;color:#444;margin-bottom:6px;">{a.get('ai_summary','')}</div>
  <div style="font-size:11px;color:#888;background:#f8f8f8;padding:6px 10px;border-radius:6px;margin-bottom:8px;">{a.get('reason','')}</div>
  <span style="font-size:11px;color:#aaa;">{a.get('source','')} · {a.get('category','')}</span>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>뉴스 브리핑 {TODAY}</title></head>
<body style="margin:0;background:#f5f5f5;font-family:-apple-system,sans-serif;">
<div style="max-width:620px;margin:0 auto;padding:20px 16px;">
  <div style="background:#111;border-radius:12px;padding:20px;margin-bottom:14px;">
    <div style="font-size:11px;color:#888;">{TODAY}</div>
    <div style="font-size:20px;font-weight:700;color:#fff;margin:4px 0;">오늘의 뉴스 브리핑</div>
    <div style="font-size:12px;color:#aaa;">{len(articles)}건 선별 · 반도체·코스피·경제 중점</div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:14px;">
    <div style="flex:1;background:#EAF3DE;border-radius:10px;padding:12px;text-align:center;">
      <div style="font-size:11px;color:#3B6D11;">호재</div>
      <div style="font-size:22px;font-weight:700;color:#27500A;">{counts['호재']}</div>
    </div>
    <div style="flex:1;background:#FCEBEB;border-radius:10px;padding:12px;text-align:center;">
      <div style="font-size:11px;color:#A32D2D;">악재</div>
      <div style="font-size:22px;font-weight:700;color:#791F1F;">{counts['악재']}</div>
    </div>
    <div style="flex:1;background:#F1EFE8;border-radius:10px;padding:12px;text-align:center;">
      <div style="font-size:11px;color:#5F5E5A;">중립</div>
      <div style="font-size:22px;font-weight:700;color:#2C2C2A;">{counts['중립']}</div>
    </div>
  </div>
  {cards}
  <div style="text-align:center;font-size:11px;color:#aaa;margin-top:16px;">
    Claude AI 자동 분석 · 투자 판단의 단독 근거로 사용 금지
  </div>
</div>
</body>
</html>"""


def send_email(html):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [r.strip() for r in os.environ.get("RECIPIENT_EMAILS", sender).split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[뉴스 브리핑] {TODAY}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password)
        s.sendmail(sender, recipients, msg.as_string())
    print(f"이메일 발송 완료 → {recipients}")


def save_web_page(html):
    d = Path("docs")
    d.mkdir(exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    (d / f"{TODAY_FILE}.html").write_text(html, encoding="utf-8")
    print("웹페이지 저장 완료")


def main():
    print(f"=== 뉴스 브리핑 시작: {TODAY} ===")
    articles = fetch_news()
    analyzed = analyze_with_claude(articles)
    html = build_html(analyzed)
    send_email(html)
    save_web_page(html)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
