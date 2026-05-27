"""
서울 도슨트 시연 스크립트
- 장소 검색 → 해설 조회 or 실시간 생성
"""
import sqlite3
from groq import Groq

DB_PATH = "/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db"
GROQ_API_KEY = "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"
MODEL = "llama-3.3-70b-versatile"

THEMES = ["생활사", "독립운동", "지명유래", "시장", "인물"]

SYSTEM_PROMPT = """당신은 서울의 역사와 문화를 생생하게 전달하는 도슨트입니다.
딱딱한 정보 전달이 아닌, 과거와 현재를 연결하는 이야기꾼 말투로 해설을 작성하세요.

예시 톤:
"조선시대 이 골목은 구리 냄새가 났대요. 놋그릇, 구리 장식품을 두드리는 소리가
하루 종일 울렸고, 관아에서 물건 사러 나온 관리들과 시장 상인들이 뒤섞였죠.
지금도 을지로 3, 4가 골목 안으로 들어가면 비슷해요. 철판 두드리는 소리, 공구 냄새.
500년 전 구리 장인들이 지금은 철물 장인으로 바뀌었을 뿐."

규칙:
- 3~5문단, 각 문단 2~4문장
- 과거 이야기로 시작해 현재와 연결
- 구체적인 감각(냄새, 소리, 풍경) 묘사 포함
- 마지막 문단: 방문자에게 지금 이 장소에서 느낄 수 있는 것
- 출력: 해설 텍스트만 (제목, 번호, 마크다운 불필요)"""


def search_places(conn, keyword):
    return conn.execute(
        "SELECT place_id, name, district, address FROM places WHERE name LIKE ? LIMIT 10",
        (f"%{keyword}%",)
    ).fetchall()


def get_existing_story(conn, place_id, theme):
    row = conn.execute(
        "SELECT docent_text FROM stories WHERE place_id=? AND theme=?",
        (place_id, theme)
    ).fetchone()
    return row[0] if row else None


def get_sources(conn, place_id):
    rows = conn.execute(
        "SELECT raw_text FROM sources WHERE place_id=?", (place_id,)
    ).fetchall()
    return "\n---\n".join(r[0] for r in rows)[:3000]


def generate_live(client, name, address, district, theme, sources_text):
    location = f"{district or ''} {address or ''}".strip() or "서울"
    theme_hints = {
        "생활사": "이 장소의 옛 생활 모습, 일상, 장인, 상인, 골목 풍경",
        "독립운동": "이 장소와 연결된 독립운동, 항일 역사, 인물과 사건",
        "지명유래": "이 장소 이름의 유래, 지명 변천, 조선시대부터 현재까지",
        "시장": "이 장소의 시장, 상업, 교역, 물건과 사람들의 이야기",
        "인물": "이 장소와 얽힌 역사적 인물, 그들의 삶과 자취",
    }
    prompt = f"""다음 장소에 대한 도슨트 해설을 작성해주세요.

장소명: {name}
위치: {location}
주제: {theme} ({theme_hints[theme]})

참고 자료:
{sources_text}

위 자료를 바탕으로 {theme} 주제의 도슨트 해설을 작성하세요."""

    print("\n  ✍️  해설 생성 중...\n")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=800,
    )
    return response.choices[0].message.content.strip()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    client = Groq(api_key=GROQ_API_KEY)

    print("=" * 60)
    print("  서울 도슨트 해설 시연")
    print("=" * 60)

    while True:
        print("\n장소명을 입력하세요 (종료: q): ", end="")
        keyword = input().strip()
        if keyword.lower() == "q":
            break

        places = search_places(conn, keyword)
        if not places:
            print("  검색 결과가 없어요.")
            continue

        print(f"\n  검색 결과 {len(places)}건:")
        for i, (pid, name, district, address) in enumerate(places, 1):
            print(f"  {i}. {name}  ({district or ''} {address or ''})")

        print("\n번호 선택: ", end="")
        try:
            idx = int(input().strip()) - 1
            place_id, name, district, address = places[idx]
        except (ValueError, IndexError):
            print("  잘못된 입력이에요.")
            continue

        print(f"\n주제를 선택하세요:")
        for i, t in enumerate(THEMES, 1):
            has = "✓" if get_existing_story(conn, place_id, t) else " "
            print(f"  {i}. [{has}] {t}")
        print("  (✓ = 저장된 해설 있음, 빈칸 = 실시간 생성)")

        print("\n번호 선택: ", end="")
        try:
            tidx = int(input().strip()) - 1
            theme = THEMES[tidx]
        except (ValueError, IndexError):
            print("  잘못된 입력이에요.")
            continue

        # 저장된 해설 있으면 바로 출력, 없으면 실시간 생성
        story = get_existing_story(conn, place_id, theme)
        if story:
            print(f"\n  📖 저장된 해설 [{theme}]\n")
        else:
            sources = get_sources(conn, place_id)
            if not sources:
                print("  소스 데이터가 없어요.")
                continue
            story = generate_live(client, name, address, district, theme, sources)
            print(f"  📖 실시간 생성 해설 [{theme}]\n")

        print("-" * 60)
        print(story)
        print("-" * 60)

    conn.close()
    print("\n종료합니다.")


if __name__ == "__main__":
    main()
