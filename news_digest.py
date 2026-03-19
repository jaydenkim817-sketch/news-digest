"""
뉴스 다이제스트 자동화 시스템 v2
"""

import os
import json
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

FOCUS_KEYWORDS = [
    "반도체", "삼성전자", "SK하이닉스", "HBM", "파운드리",
    "코스피", "외국인 수급", "코스닥", "지수",
    "미중 관세", "환율", "달러", "위안화", "무역분쟁",
    "미국 경제", "한국 경제", "GDP", "금리", "연준", "FOMC", "한국은행",
    "AI", "엔비디아", "인공지능", "데이터센터",
]

RSS_FEEDS = [
    {"url": "https://feeds.feedburner.com/TechCrunch", "category": "IT/테크", "source": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "category": "IT/테크", "source": "The Verge"},
    {"url": "https://zdnet.co.kr/rss/latest/", "category": "IT/테크", "source": "ZDNet Korea"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "category": "경제/금융", "source": "Bloomberg"},
    {"url": "https://www.hankyung.com/feed/all-news", "category": "경제/금융", "source": "한국경제"},
    {"url": "https://www.mk.co.kr/rss/40300001/", "category": "경제/금융", "source": "매일경제"},
    {"url": "https://feeds.reuters.com/reuters/businessNews", "category": "글로벌", "source": "Reuters"},
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "category": "글로벌", "source": "WSJ Markets"},
]

MAX_ARTICLES_PER_FEED = 5
MAX_ARTICLES_TOTAL = 20  # Claude 부하 줄이기 위해 20으로 제한
TOP_N_ARTICLES = 5       # 선별 기사도 5개로 줄임


def fetch_news() -> list[dict]:
    articles = []
    cutoff = datetime.now(KST) - timedelta(hours=24)

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= MAX_ARTICLES_PER_FEED:
                    break
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
                if published and published < cutoff:
                    continue
                articles.append({
                    "title": entry.get("title", "").strip()[:100],  # 제목 길이 제한
                    "link": entry.get("link", ""),
                    "source": feed_info["source"],
                    "category": feed_info["category"],
                    "published": published.strftime("%H:%M") if published else "",
                })
                count += 1
            print(f"  {feed_info['source']}: {count}건 수집")
        except Exception as e:
            print(f"  {feed_info['source']} 수집 실패: {e}")

    seen = set()
    unique = []
    for a in articles:
        key = a["title"][:30]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    print(f"\n총 {len(unique)}건 수집 완료")
    return unique[:MAX_ARTICLES_TOTAL]


def analyze_with_claude(articles: list[dict]) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # 기사 목록을 짧게 만들기
    articles_text = ""
    for i, a in enumerate(articles):
        articles_text += f"[{i+1}] {a['title']} ({a['source']})\n"

    prompt = f"""다음 뉴스에서 반도체/코스피/환율/금리/AI 관련 중요 뉴스 {TOP_N_ARTICLES}개를 골라 분석하세요.

뉴스 목록:
{articles_text}

반드시 아래 JSON 형식만 출력하세요. 다른 텍스트 없이 JSON만:
{{"articles":[{{"index":1,"summary":"2줄 요약","signal":"호재","reason":"근거 1문장"}},{{"index":2,"summary":"2줄 요약","signal":"악재","reason":"근거 1문장"}}]}}

signal은 반드시 호재/악재/중립 중 하나."""

    print("Claude API 분석 중...")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # JSON 추출
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # JSON 시작/끝 찾기
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    result = json.loads(raw)
    analyzed = []
    for item in result["articles"]:
        idx = item["index"] - 1
        if 0 <= idx < len(articles):
            article = articles[idx].copy()
            article["ai_summary"] = item.get("summary", "")
            article["signal"] = item.get("signal", "중립")
            article["reason"] = item.get("reason", "")
            analyzed.append(article)

    print(f"Claude 분석 완료: {len(analyzed)}건 선별")
    return analyzed


SIGNAL_STYLE = {
    "호재": ("호재", "#3B6D11", "#EAF3DE"),
    "악재": ("악재", "#A32D2D", "#FCEBEB"),
    "중립": ("중립", "#5F5E5A", "#F1EFE8"),
}

def build_html(articles: list[dict], is_email: bool = False) -> str:
    counts = {"호재": 0, "악재": 0, "중립": 0}
    for a in articles:
        sig = a.get("signal", "중립")
        if sig in counts:
            counts[sig] += 1

    cards_html = ""
    for a in articles:
        sig = a.get("signal", "중립")
        label, text_color, bg_color = SIGNAL_STYLE.get(sig, SIGNAL_STYLE["중립"])
        summary = a.get("ai_summary", "").replace("\n", "<br>")
        cards_html += f"""
        <div style="border:1px solid #e5e5e5;border-radius:12px;padding:16px 18px;margin-bottom:12px;background:#ffffff;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:8px;">
            <div style="font-size:14px;font-weight:600;color:#111111;line-height:1.5;flex:1;">
              <a href="{a['link']}" style="color:#111111;text-decoration:none;">{a['title']}</a>
            </div>
            <span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap;color:{text_color};background:{bg_color};">{label}</span>
          </div>
          <div style="font-size:13px;color:#444444;line-height:1.7;margin-bottom:8px;">{summary}</div>
          <div style="font-size:11px;color:#888888;padding:6px 10px;background:#f8f8f8;border-radius:6px;margin-bottom:8px;">{a.get('reason','')}</div>
          <div style="display:flex;gap:8px;align-items:center;">
            <span style="font-size:11px;color:#aaaaaa;">{a.get('source','')}</span>
            <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:#f0f0f0;color:#555555;">{a.get('category','')}</span>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>뉴스 브리핑 {TODAY}</title></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:20px 16px;">
  <div style="background:#111111;border-radius:12px;padding:20px 24px;margin-bottom:16px;">
    <div style="font-size:11px;color:#888888;margin-bottom:4px;">{TODAY}</div>
    <div style="font-size:20px;font-weight:700;color:#ffffff;">오늘의 뉴스 브리핑</div>
    <div style="font-size:12px;color:#aaaaaa;margin-top:4px;">총 {len(articles)}건 선별</div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:16px;">
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
  {cards_html}
  <div style="text-align:center;font-size:11px;color:#aaaaaa;margin-top:20px;">
    본 브리핑은 Claude AI 자동 분석 참고용입니다. 투자 판단의 단독 근거로 사용하지 마세요.
  </div>
</div>
</body>
</html>"""


def send_email(html_content: str):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients_raw = os.environ.get("RECIPIENT_EMAILS", sender)
    recipients = [r.strip() for r in recipients_raw.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[뉴스 브리핑] {TODAY}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())

    print(f"이메일 발송 완료 → {recipients}")


def save_web_page(html_content: str):
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "index.html").write_text(html_content, encoding="utf-8")
    (docs_dir / f"{TODAY_FILE}.html").write_text(html_content, encoding="utf-8")
    print(f"웹페이지 저장 완료 → docs/index.html")


def main():
    print(f"\n{'='*50}")
    print(f"뉴스 브리핑 시작: {TODAY}")
    print(f"{'='*50}\n")

    print("[1/4] 뉴스 수집 중...")
    articles = fetch_news()
    if not articles:
        print("수집된 뉴스가 없습니다.")
        return

    print("\n[2/4] AI 분석 중...")
    analyzed = analyze_with_claude(articles)

    print("\n[3/4] HTML 생성 중...")
    html = build_html(analyzed)

    print("\n[4/4] 발송 및 저장 중...")
    send_email(html)
    save_web_page(html)

    print(f"\n완료!")


if __name__ == "__main__":
    main()
