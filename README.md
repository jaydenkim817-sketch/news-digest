# 뉴스 브리핑 자동화 시스템

매일 오전 8시 IT/테크·경제·글로벌 뉴스를 수집하고,
Claude AI가 반도체·코스피·미중 정정·한미 경제 관점에서
호재/악재를 판단해 Gmail로 발송 + GitHub Pages에 게시합니다.

---

## 파일 구조

```
├── news_digest.py                    ← 메인 스크립트
├── .github/
│   └── workflows/
│       └── news_digest.yml           ← GitHub Actions 자동화
└── docs/
    ├── index.html                    ← GitHub Pages 최신 브리핑
    └── 2025-03-19.html               ← 날짜별 아카이브
```

---

## 설치 및 설정 (5단계)

### 1단계 — GitHub 저장소 만들기

1. GitHub에서 새 저장소(repository) 생성
2. 위 파일 3개를 업로드하거나 `git push`

### 2단계 — GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions → **New repository secret**

| Secret 이름 | 값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic Console에서 발급 |
| `GMAIL_ADDRESS` | `yourname@gmail.com` | 발송에 사용할 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | 앱 비밀번호 16자리 | 아래 3단계 참고 |
| `RECIPIENT_EMAILS` | `a@gmail.com,b@gmail.com` | 수신자 (쉼표로 여러 명 가능) |

### 3단계 — Gmail 앱 비밀번호 발급

일반 Gmail 비밀번호는 사용 불가. 앱 전용 비밀번호가 필요합니다.

1. Google 계정 → **보안** 탭
2. **2단계 인증** 켜기 (필수)
3. 검색창에 "앱 비밀번호" 입력 → 생성
4. 앱: 메일 / 기기: Windows 컴퓨터 → **생성**
5. 표시된 16자리 비밀번호를 `GMAIL_APP_PASSWORD`에 입력

### 4단계 — GitHub Pages 활성화

저장소 → Settings → Pages → Source: **Deploy from a branch**
Branch: `main` / Folder: `/docs` → Save

웹 주소: `https://[내아이디].github.io/[저장소이름]`

### 5단계 — 첫 테스트 실행

저장소 → Actions 탭 → "뉴스 브리핑 자동 발송" → **Run workflow**

정상 동작하면 이후 매일 오전 8시 자동 실행됩니다.

---

## 커스터마이징

`news_digest.py` 상단의 설정값을 수정하세요.

```python
# 발송 시각 변경: .github/workflows/news_digest.yml 의 cron 값 수정
# 오전 7시 → '0 22 * * *'
# 오전 9시 → '0 0 * * *'

# 키워드 추가/변경
FOCUS_KEYWORDS = [
    "반도체", "삼성전자", ...  # 원하는 키워드 추가
]

# RSS 피드 추가
RSS_FEEDS = [
    {"url": "피드 URL", "category": "카테고리", "source": "출처 이름"},
    ...
]

# 선별 기사 수 조정
TOP_N_ARTICLES = 8   # 더 많이 보고 싶으면 10~15로 변경
```

---

## 예상 비용

| 항목 | 비용 |
|---|---|
| GitHub Actions | 무료 (퍼블릭 저장소 기준) |
| GitHub Pages | 무료 |
| Anthropic API | 약 $0.01~0.03 / 1회 실행 → 월 $0.3~1 수준 |
| Gmail SMTP | 무료 |

---

## 주의사항

- 본 브리핑은 AI 자동 분석 결과로, 투자 판단의 단독 근거로 사용하지 마세요.
- RSS 피드 주소는 사이트 정책에 따라 변경될 수 있습니다.
- Gmail 앱 비밀번호는 외부에 노출되지 않도록 반드시 Secrets에만 저장하세요.
