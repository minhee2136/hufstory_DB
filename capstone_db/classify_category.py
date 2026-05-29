"""
장소 카테고리 분류기 v2
- 9개 카테고리: 궁궐과 왕실 / 골목 / 지명 / 문화·예술 / 독립운동 / 시장과 생활 / 자연과 공원 / 근대 역사 / 인물 이야기
- 장소명 매칭 가중치 >> 텍스트 매칭 가중치
- 장소명 직접 패턴 우선 분류
"""

import sqlite3
import json
import re
from collections import defaultdict
from konlpy.tag import Okt

# ── 1. 장소명 직접 패턴 (최우선 적용) ────────────────────────────
NAME_PATTERNS = {
    '독립운동': [
        # 장소 자체가 독립운동 관련인 것만 (광복/일제 등 단어는 근대역사와 겹쳐서 제외)
        '형무소', '감옥', '의거', '임시정부', '만세운동',
        '안중근', '유관순', '윤봉길', '김구', '이봉창', '신채호', '이준',
        '손병희', '한용운', '이회영', '이상설', '홍범도', '김좌진',
        '탑골공원', '봉황각', '경교장', '백범기념', '독립기념',
        '3·1운동', '삼일운동',
    ],
    '궁궐과 왕실': [
        '경복궁', '창덕궁', '창경궁', '덕수궁', '경희궁', '경운궁', '운현궁',
        '종묘', '사직', '동궐', '서궐', '법궁', '이궁', '행궁',
        '정전', '편전', '침전', '내전', '외전', '전각',
        '근정전', '인정전', '명정전', '중화전', '함녕전',
        '광화문', '돈화문', '홍화문', '숭정문',
    ],
    '시장과 생활': [
        '시장', '장터', '시전', '육의전', '보부상', '오일장',
        '수산시장', '약령시장', '건어물', '화훼',
    ],
    '자연과 공원': [
        '공원', '광장', '정원', '수목원', '생태공원',
        '북한산', '남산', '인왕산', '관악산', '도봉산', '수락산',
        '한강', '청계천', '중랑천', '홍제천', '탄천',
        '약수터', '폭포',
    ],
    '문화·예술': [
        '미술관', '갤러리', '박물관', '기념관', '전시관', '전시실',
        '극장', '공연장', '문화원', '문화재단', '아트센터',
        '도서관', '기록관', '아카이브',
        '석탑', '탑', '불상', '석등', '부도', '마애불', '사지', '절터',
    ],
    '근대 역사': [
        '총독부', '경성', '조선은행', '한성', '전차', '철도',
        '성당', '교회', '학당', '병원', '신문사',
        '을사', '갑오', '개화', '근대',
        '딜쿠샤', '가옥', '구청사', '구본관', '구교사', '구건물',
    ],
    '인물 이야기': [
        '생가', '고택', '묘역', '서원', '위패',  # 사당 제거 (사당동 오탐)
        '정약용', '박지원', '이황', '이이', '허준', '김정호',
        '세종', '이순신', '황희', '성삼문', '사육신', '생육신',
    ],
}

# ── 2. 텍스트 키워드 (보조 점수) ────────────────────────────────
TEXT_KEYWORDS = {
    '궁궐과 왕실': [
        '궁궐', '궁', '왕', '왕실', '왕조', '임금', '왕비', '태조', '세종', '고종',
        '편전', '침전', '법궁', '전각', '왕세자', '대비',
    ],
    '골목': [
        '골목', '길', '거리', '로', '도로', '보도', '지하도', '육교', '터널',
        '고개', '다리', '교량', '나루', '포구', '항', '진',
        '가로', '통', '대로', '소로',
    ],
    '지명': [
        '동', '방', '계', '리', '가', '촌', '원', '정', '포',
        '지명', '옛 이름', '불리', '유래', '마을',
    ],
    '문화·예술': [
        '미술', '예술', '전시', '공연', '음악', '연극', '무용', '조각', '회화',
        '문학', '출판', '방송', '영화', '사진', '공예',
    ],
    '독립운동': [
        '독립', '독립운동', '항일', '의병', '만세운동', '삼일운동', '임시정부',
        '광복', '애국', '순국', '열사', '의사', '지사', '민족운동',
        '일제', '식민지', '항거', '저항',
    ],
    '시장과 생활': [
        '시장', '상인', '상업', '장사', '가게', '생활', '생활사',
        '민생', '민속', '풍속', '음식', '식문화', '보부상', '시전',
    ],
    '자연과 공원': [
        '공원', '숲', '산', '계곡', '폭포', '약수', '하천', '강',
        '나무', '수목', '식물', '꽃', '생태', '자연', '녹지',
        '등산로', '산책로', '둘레길',
    ],
    '근대 역사': [
        '근대', '개화', '구한말', '대한제국', '일제강점기', '경성',
        '서양식', '양관', '선교사', '개항', '조약', '문물',
        '1900', '1910', '1920', '1930',
    ],
    '인물 이야기': [
        '인물', '위인', '선생', '장군', '학자', '문인', '시인',
        '묘', '묘역', '생가', '고택', '기념비', '동상', '흉상',
        '유물', '유품', '업적', '출생',
    ],
}

# ── 3. 골목 vs 지명 구분 패턴 ────────────────────────────────────
GOLMOK_NAME_PATTERNS = ['길', '로', '거리', '골목', '고개', '다리', '나루', '포', '진', '도로', '보도', '육교', '지하도', '터널']
JIMYEONG_NAME_PATTERNS = ['동', '방', '계', '리', '가', '동네', '마을', '촌', '구역', '지역', '원', '정']


def classify_by_name(name):
    """장소명 패턴으로 우선 분류. 매칭 없으면 None 반환"""
    if not name:
        return None
    for category, patterns in NAME_PATTERNS.items():
        for pat in patterns:
            if pat in name:
                return category
    return None


def classify_golmok_or_jimyeong(name, text):
    """골목과 지명을 세분화"""
    if name:
        for pat in GOLMOK_NAME_PATTERNS:
            if name.endswith(pat) or pat in name:
                return '골목'
        for pat in JIMYEONG_NAME_PATTERNS:
            if name.endswith(pat):
                return '지명'
    # 텍스트 기반
    if text:
        golmok_score = sum(1 for p in ['길', '거리', '골목', '고개', '다리'] if p in text)
        jimyeong_score = sum(1 for p in ['지명', '마을', '동네', '불리', '유래'] if p in text)
        if golmok_score > jimyeong_score:
            return '골목'
    return '지명'


def extract_nouns(text, okt):
    if not text:
        return []
    try:
        return okt.nouns(text[:500])
    except:
        return []


def classify(name, sources_json, okt):
    # 1순위: 장소명 직접 패턴
    name_cat = classify_by_name(name)
    if name_cat:
        return name_cat

    # 텍스트 수집
    texts = [name or '']
    if sources_json:
        src = json.loads(sources_json)
        for v in src.values():
            if v:
                texts.append(v[:400])
    full_text = ' '.join(texts)
    nouns = set(extract_nouns(full_text, okt))

    # 2순위: 텍스트 키워드 점수
    scores = defaultdict(int)
    for category, keywords in TEXT_KEYWORDS.items():
        for kw in keywords:
            if kw in nouns:
                scores[category] += 3
            if kw in full_text:
                scores[category] += 1

    if scores:
        best = max(scores, key=lambda k: scores[k])
        if scores[best] >= 3:
            # 독립운동은 텍스트만으로는 높은 점수 필요 (근대역사와 혼동 방지)
            if best == '독립운동' and scores[best] < 8:
                sorted_cats = sorted(scores, key=lambda k: scores[k], reverse=True)
                best = sorted_cats[1] if len(sorted_cats) > 1 and scores[sorted_cats[1]] >= 2 else '근대 역사'
            # 골목과 지명은 세분화
            if best in ('골목', '지명'):
                return classify_golmok_or_jimyeong(name, full_text)
            return best

    # 기본값: 골목 vs 지명 세분화
    return classify_golmok_or_jimyeong(name, full_text)


def main():
    okt = Okt()
    conn = sqlite3.connect('capstone_db/seoul_docent.db')
    cur = conn.cursor()

    cur.execute('SELECT place_id, name, sources FROM places')
    rows = cur.fetchall()

    results = defaultdict(int)
    for place_id, name, sources in rows:
        category = classify(name, sources, okt)
        cur.execute('UPDATE places SET category = ? WHERE place_id = ?', (category, place_id))
        results[category] += 1

    conn.commit()
    conn.close()

    print('=== 분류 결과 ===')
    for cat, cnt in sorted(results.items(), key=lambda x: -x[1]):
        print(f'  {cat}: {cnt}건')
    print(f'  합계: {sum(results.values())}건')


if __name__ == '__main__':
    main()
