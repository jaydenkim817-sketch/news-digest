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
TODAY_DOW = ["월", "화", "수", "목", "금", "토", "일"][datetime.now(KST).weekday()]
TODAY_FILE = datetime.now(KST).strftime("%Y-%m-%d")

RSS_FEEDS = [
    {"url": "https://feeds.feedburner.com/TechCrunch", "category": "IT/테크", "source": "TechCrunch", "lang": "en"},
    {"url": "https://www.theverge.com/rss/index.xml", "category": "IT/테크", "source": "The Verge", "lang": "en"},
    {"url": "https://zdnet.co.kr/rss/latest/", "category": "IT/테크", "source": "ZDNet Korea", "lang": "ko"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "category": "경제/금융", "source": "Bloomberg", "lang": "en"},
    {"url": "https://www.hankyung.com/feed/all-news", "category": "경제/금융", "source": "한국경제", "lang": "ko"},
    {"url": "https://www.mk.co.kr/rss/40300001/", "category": "경제/금융", "source": "매일경제", "lang": "ko"},
    {"url": "https://feeds.reuters.com/reuters/businessNews", "category": "글로벌", "source": "Reuters", "lang": "en"},
]

TOP_N = 10


def fetch_news():
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= 5:
                    break
                title = entry.get("title", "").strip()[:120]
                if not title:
                    continue
                # 본문 최대한 가져오기
                body = ""
                if hasattr(entry, "content") and entry.content:
                    body = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    body = entry.get("summary", "")
                # HTML 태그 제거
                body = re.sub(r"<[^>]+>", " ", body)
                body = re.sub(r"\s+", " ", body).strip()[:600]

                articles.append({
                    "title": title,
                    "body": body,
                    "link": entry.get("link", ""),
                    "source": feed_info["source"],
                    "category": feed_info["category"],
                    "lang": feed_info["lang"],
                })
                count += 1
            print(f"  {feed_info['source']}: {count}건")
        except Exception as e:
            print(f"  {feed_info['source']} 실패: {e}")

    seen = set()
    unique = []
    for a in articles:
        key = a["title"][:30]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    print(f"총 {len(unique)}건 수집")
    return unique[:25]


def analyze_with_claude(articles):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    lines = "\n".join([
        f"{i+1}. [{a['category']}][{a['source']}] {a['title']}"
        for i, a in enumerate(articles)
    ])

    prompt = f"""아래 뉴스 중 반도체/코스피/금리/AI/환율/미중관세/한국경제/미국경제 관련 중요 뉴스 {TOP_N}개를 골라주세요.
IT/테크와 경제/금융 카테고리를 골고루 포함해주세요.

각 뉴스마다 반드시 아래 형식으로만 작성하세요:

번호: [원본 번호]
요약: [핵심 내용 1-2문장, 한국어]
신호: [호재 또는 악재 또는 중립]
근거: [왜 호재/악재/중립인지 1문장]

{lines}"""

    print("Claude 1차 분석 중 (선별)...")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    # 선별된 기사 파싱
    selected = []
    blocks = re.split(r'\n(?=번호:)', raw)
    for block in blocks:
        try:
            num_m = re.search(r'번호:\s*(\d+)', block)
            sum_m = re.search(r'요약:\s*(.+?)(?=\n신호:|\Z)', block, re.DOTALL)
            sig_m = re.search(r'신호:\s*(호재|악재|중립)', block)
            rea_m = re.search(r'근거:\s*(.+)', block)
            if not (num_m and sum_m and sig_m):
                continue
            idx = int(num_m.group(1)) - 1
            if 0 <= idx < len(articles):
                article = articles[idx].copy()
                article["ai_summary"] = sum_m.group(1).strip().replace("\n", " ")
                article["signal"] = sig_m.group(1).strip()
                article["reason"] = rea_m.group(1).strip() if rea_m else ""
                article["translation"] = ""
                selected.append(article)
        except Exception:
            continue

    print(f"선별 완료: {len(selected)}건")

    # 2차: 번역 요약 생성
    print("Claude 2차 분석 중 (번역 요약)...")
    for i, article in enumerate(selected):
        try:
            content = article["title"]
            if article["body"]:
                content += "\n\n" + article["body"]

            if article["lang"] == "en":
                trans_prompt = f"""다음 영문 뉴스를 한국어로 3~5줄로 번역 요약해주세요.
핵심 사실, 배경, 시장 영향 순으로 자연스럽게 정리해주세요.
번역 요약문만 출력하고 다른 텍스트는 쓰지 마세요.

{content}"""
            else:
                trans_prompt = f"""다음 뉴스를 3~5줄로 상세 요약해주세요.
핵심 사실, 배경, 시장 영향 순으로 자연스럽게 정리해주세요.
요약문만 출력하고 다른 텍스트는 쓰지 마세요.

{content}"""

            trans_resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": trans_prompt}],
            )
            article["translation"] = trans_resp.content[0].text.strip()
            print(f"  번역 완료: {i+1}/{len(selected)}")
        except Exception as e:
            print(f"  번역 실패: {e}")
            article["translation"] = ""

    return selected if selected else articles[:5]


def build_html(articles):
    counts = {"호재": 0, "악재": 0, "중립": 0}
    for a in articles:
        sig = a.get("signal", "중립")
        if sig in counts:
            counts[sig] += 1

    categories = {}
    for a in articles:
        cat = a.get("category", "기타")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(a)

    SIGNAL_COLOR = {
        "호재": {"dot": "#22c55e", "bg": "#f0fdf4", "text": "#15803d", "border": "#bbf7d0"},
        "악재": {"dot": "#ef4444", "bg": "#fef2f2", "text": "#dc2626", "border": "#fecaca"},
        "중립": {"dot": "#94a3b8", "bg": "#f8fafc", "text": "#64748b", "border": "#e2e8f0"},
    }

    cat_icon = {"IT/테크": "◆", "경제/금융": "◈", "글로벌": "◉", "기타": "◇"}

    sections_html = ""
    card_idx = 0

    for cat, items in categories.items():
        cards_html = ""
        for a in items:
            sig = a.get("signal", "중립")
            c = SIGNAL_COLOR.get(sig, SIGNAL_COLOR["중립"])
            translation = a.get("translation", "")
            card_idx += 1
            cid = f"t{card_idx}"

            trans_block = ""
            if translation:
                trans_block = f"""
<button class="expand-btn" onclick="toggle('{cid}')">
  <span style="display:flex;align-items:center;gap:6px;">
    <span style="font-size:11px;">&#127760;</span>
    {'번역 ' if a.get('lang') == 'en' else ''}상세 요약 보기
  </span>
  <span class="chevron" id="c{card_idx}">&#9660;</span>
</button>
<div class="expand-content" id="{cid}">
  <div style="background:#f8fafc;border-radius:8px;padding:14px;margin-top:10px;">
    <div style="font-size:9px;font-weight:700;letter-spacing:0.1em;color:#94a3b8;text-transform:uppercase;margin-bottom:8px;">{'번역 요약' if a.get('lang') == 'en' else '상세 요약'} · {a.get('source','')}</div>
    <p style="font-size:12px;color:#334155;line-height:1.85;margin:0;">{translation}</p>
  </div>
</div>"""

            cards_html += f"""
<div style="background:#ffffff;border:1px solid #f1f5f9;border-radius:12px;padding:18px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px;">
    <a href="{a['link']}" style="font-size:14px;font-weight:600;color:#0f172a;text-decoration:none;line-height:1.5;flex:1;">{a['title']}</a>
    <span style="display:flex;align-items:center;gap:4px;font-size:10px;font-weight:700;padding:3px 9px;border-radius:20px;white-space:nowrap;flex-shrink:0;color:{c['text']};background:{c['bg']};border:1px solid {c['border']};">
      <span style="width:5px;height:5px;border-radius:50%;background:{c['dot']};display:inline-block;"></span>{sig}
    </span>
  </div>
  <p style="font-size:12px;color:#475569;line-height:1.7;margin:0 0 10px;">{a.get('ai_summary','')}</p>
  <div style="background:{c['bg']};border-left:3px solid {c['dot']};padding:7px 11px;border-radius:0 6px 6px 0;margin-bottom:12px;">
    <p style="font-size:11px;color:{c['text']};margin:0;line-height:1.6;">{a.get('reason','')}</p>
  </div>
  {trans_block}
  <div style="display:flex;align-items:center;gap:8px;margin-top:12px;">
    <span style="font-size:10px;color:#94a3b8;">{a.get('source','')}</span>
    <span style="font-size:10px;color:#94a3b8;background:#f1f5f9;padding:2px 8px;border-radius:10px;">{cat}</span>
  </div>
</div>"""

        icon = cat_icon.get(cat, "◇")
        sections_html += f"""
<div style="margin-bottom:32px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;padding-bottom:10px;border-bottom:2px solid #f1f5f9;">
    <span style="font-size:12px;color:#94a3b8;">{icon}</span>
    <span style="font-size:11px;font-weight:700;color:#0f172a;letter-spacing:0.05em;text-transform:uppercase;">{cat}</span>
    <span style="font-size:10px;color:#cbd5e1;margin-left:auto;">{len(items)}건</span>
  </div>
  {cards_html}
</div>"""

    expand_css = """
<style>
.expand-btn {
  display:flex; align-items:center; justify-content:space-between;
  background:none; border:1px solid #e2e8f0; border-radius:8px;
  padding:8px 12px; cursor:pointer; font-size:11px; color:#64748b;
  font-weight:500; width:100%; margin-bottom:0; transition:all 0.15s;
}
.expand-btn:hover { background:#f8fafc; border-color:#cbd5e1; }
.expand-content {
  overflow:hidden; max-height:0; opacity:0;
  transition:max-height 0.35s ease, opacity 0.3s ease;
}
.expand-content.open { max-height:500px; opacity:1; }
.chevron { transition:transform 0.2s; display:inline-block; font-size:10px; }
.chevron.open { transform:rotate(180deg); }
</style>
<script>
function toggle(id) {
  const el = document.getElementById(id);
  const num = id.replace('t','');
  const ch = document.getElementById('c'+num);
  const isOpen = el.classList.contains('open');
  el.classList.toggle('open', !isOpen);
  ch.classList.toggle('open', !isOpen);
}
</script>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>뉴스 브리핑 {TODAY}</title>
{expand_css}
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;">
<div style="max-width:620px;margin:0 auto;padding:24px 16px;">

  <div style="margin-bottom:24px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;">
      <div>
        <div style="font-size:10px;font-weight:700;letter-spacing:0.1em;color:#94a3b8;text-transform:uppercase;margin-bottom:6px;">Daily Briefing</div>
        <div style="font-size:24px;font-weight:700;color:#0f172a;letter-spacing:-0.02em;line-height:1.2;">{TODAY}<br><span style="color:#94a3b8;font-size:16px;">({TODAY_DOW}요일)</span></div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:10px;color:#cbd5e1;margin-bottom:4px;">총 선별</div>
        <div style="font-size:26px;font-weight:700;color:#0f172a;">{len(articles)}<span style="font-size:12px;color:#94a3b8;font-weight:400;">건</span></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
      <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:9px;font-weight:700;letter-spacing:0.08em;color:#15803d;text-transform:uppercase;margin-bottom:4px;">호재</div>
        <div style="font-size:24px;font-weight:700;color:#15803d;">{counts['호재']}</div>
      </div>
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:9px;font-weight:700;letter-spacing:0.08em;color:#dc2626;text-transform:uppercase;margin-bottom:4px;">악재</div>
        <div style="font-size:24px;font-weight:700;color:#dc2626;">{counts['악재']}</div>
      </div>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:9px;font-weight:700;letter-spacing:0.08em;color:#64748b;text-transform:uppercase;margin-bottom:4px;">중립</div>
        <div style="font-size:24px;font-weight:700;color:#64748b;">{counts['중립']}</div>
      </div>
    </div>
  </div>

  <div style="border-top:1px solid #e2e8f0;margin-bottom:28px;"></div>

  {sections_html}

  <div style="border-top:1px solid #f1f5f9;padding-top:20px;text-align:center;">
    <p style="font-size:11px;color:#cbd5e1;margin:0;line-height:1.8;">
      본 브리핑은 Claude AI가 자동 분석한 참고용 자료입니다.<br>
      투자 판단의 단독 근거로 사용하지 마세요.
    </p>
  </div>
</div>
</body>
</html>"""


def build_email_html(articles):
    """이메일용 HTML - 번역 요약을 펼친 상태로 포함"""
    counts = {"호재": 0, "악재": 0, "중립": 0}
    for a in articles:
        sig = a.get("signal", "중립")
        if sig in counts:
            counts[sig] += 1

    categories = {}
    for a in articles:
        cat = a.get("category", "기타")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(a)

    SIGNAL_COLOR = {
        "호재": {"dot": "#22c55e", "bg": "#f0fdf4", "text": "#15803d", "border": "#bbf7d0"},
        "악재": {"dot": "#ef4444", "bg": "#fef2f2", "text": "#dc2626", "border": "#fecaca"},
        "중립": {"dot": "#94a3b8", "bg": "#f8fafc", "text": "#64748b", "border": "#e2e8f0"},
    }
    cat_icon = {"IT/테크": "◆", "경제/금융": "◈", "글로벌": "◉", "기타": "◇"}

    sections_html = ""
    for cat, items in categories.items():
        cards_html = ""
        for a in items:
            sig = a.get("signal", "중립")
            c = SIGNAL_COLOR.get(sig, SIGNAL_COLOR["중립"])
            translation = a.get("translation", "")
            trans_block = ""
            if translation:
                trans_block = f"""
<div style="background:#f8fafc;border-radius:8px;padding:12px;margin-top:10px;">
  <div style="font-size:9px;font-weight:700;letter-spacing:0.1em;color:#94a3b8;text-transform:uppercase;margin-bottom:6px;">{'번역 요약' if a.get('lang') == 'en' else '상세 요약'} · {a.get('source','')}</div>
  <p style="font-size:12px;color:#334155;line-height:1.85;margin:0;">{translation}</p>
</div>"""

            cards_html += f"""
<div style="background:#ffffff;border:1px solid #f1f5f9;border-radius:12px;padding:16px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:10px;">
    <a href="{a['link']}" style="font-size:14px;font-weight:600;color:#0f172a;text-decoration:none;line-height:1.5;flex:1;">{a['title']}</a>
    <span style="font-size:10px;font-weight:700;padding:3px 9px;border-radius:20px;white-space:nowrap;flex-shrink:0;color:{c['text']};background:{c['bg']};border:1px solid {c['border']};">{sig}</span>
  </div>
  <p style="font-size:12px;color:#475569;line-height:1.7;margin:0 0 10px;">{a.get('ai_summary','')}</p>
  <div style="background:{c['bg']};border-left:3px solid {c['dot']};padding:7px 11px;border-radius:0 6px 6px 0;margin-bottom:10px;">
    <p style="font-size:11px;color:{c['text']};margin:0;">{a.get('reason','')}</p>
  </div>
  {trans_block}
  <div style="margin-top:10px;">
    <span style="font-size:10px;color:#94a3b8;">{a.get('source','')} · {cat}</span>
  </div>
</div>"""

        icon = cat_icon.get(cat, "◇")
        sections_html += f"""
<div style="margin-bottom:28px;">
  <div style="border-bottom:2px solid #f1f5f9;padding-bottom:8px;margin-bottom:12px;">
    <span style="font-size:11px;font-weight:700;color:#0f172a;letter-spacing:0.05em;">{icon} {cat.upper()}</span>
    <span style="font-size:10px;color:#cbd5e1;margin-left:8px;">{len(items)}건</span>
  </div>
  {cards_html}
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>뉴스 브리핑 {TODAY}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;">
<div style="max-width:620px;margin:0 auto;padding:24px 16px;">
  <div style="margin-bottom:20px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.1em;color:#94a3b8;text-transform:uppercase;margin-bottom:6px;">Daily Briefing</div>
    <div style="font-size:22px;font-weight:700;color:#0f172a;">{TODAY} ({TODAY_DOW}요일)</div>
  </div>
  <div style="display:table;width:100%;margin-bottom:20px;">
    <div style="display:table-cell;width:33%;padding-right:4px;">
      <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:9px;font-weight:700;color:#15803d;">호재</div>
        <div style="font-size:22px;font-weight:700;color:#15803d;">{counts['호재']}</div>
      </div>
    </div>
    <div style="display:table-cell;width:33%;padding:0 2px;">
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:9px;font-weight:700;color:#dc2626;">악재</div>
        <div style="font-size:22px;font-weight:700;color:#dc2626;">{counts['악재']}</div>
      </div>
    </div>
    <div style="display:table-cell;width:33%;padding-left:4px;">
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:9px;font-weight:700;color:#64748b;">중립</div>
        <div style="font-size:22px;font-weight:700;color:#64748b;">{counts['중립']}</div>
      </div>
    </div>
  </div>
  <div style="border-top:1px solid #e2e8f0;margin-bottom:24px;"></div>
  {sections_html}
  <div style="border-top:1px solid #f1f5f9;padding-top:16px;text-align:center;">
    <p style="font-size:10px;color:#cbd5e1;margin:0;line-height:1.8;">Claude AI 자동 분석 · 투자 판단의 단독 근거로 사용 금지</p>
  </div>
</div>
</body>
</html>"""


def send_email(html):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [r.strip() for r in os.environ.get("RECIPIENT_EMAILS", sender).split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[뉴스 브리핑] {TODAY} ({TODAY_DOW}) — 반도체·코스피·경제"
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
    web_html = build_html(analyzed)
    email_html = build_email_html(analyzed)
    send_email(email_html)
    save_web_page(web_html)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
