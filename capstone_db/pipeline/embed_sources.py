"""
Phase 3.5 — sources 임베딩 생성
sources.raw_text → sentence-transformers → DB embeddings 테이블 + FAISS 인덱스

모델: jhgan/ko-sroberta-multitask (한국어 특화)
      fallback: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
"""

import sqlite3
import numpy as np
import pickle
from pathlib import Path
from tqdm import tqdm

DB_PATH = Path("/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db")
FAISS_INDEX_PATH = DB_PATH.parent / "faiss_index.bin"
META_PATH = DB_PATH.parent / "faiss_meta.pkl"

# 한국어 특화 모델 우선, 없으면 다국어 모델
MODEL_NAME = "jhgan/ko-sroberta-multitask"
FALLBACK_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

BATCH_SIZE = 64


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_embeddings_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            source_id  INTEGER PRIMARY KEY,
            place_id   TEXT NOT NULL,
            model_name TEXT NOT NULL,
            embedding  BLOB NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        )
    """)
    conn.commit()


def load_model():
    from sentence_transformers import SentenceTransformer
    try:
        print(f"모델 로딩: {MODEL_NAME}")
        model = SentenceTransformer(MODEL_NAME)
        return model, MODEL_NAME
    except Exception as e:
        print(f"기본 모델 로딩 실패: {e}")
        print(f"fallback 모델 사용: {FALLBACK_MODEL}")
        model = SentenceTransformer(FALLBACK_MODEL)
        return model, FALLBACK_MODEL


def fetch_unembedded_sources(conn, model_name):
    """아직 임베딩되지 않은 소스만 가져옴"""
    rows = conn.execute("""
        SELECT s.source_id, s.place_id, s.raw_text
        FROM sources s
        LEFT JOIN embeddings e
          ON s.source_id = e.source_id AND e.model_name = ?
        WHERE e.source_id IS NULL
          AND s.raw_text IS NOT NULL
          AND TRIM(s.raw_text) != ''
        ORDER BY s.source_id
    """, (model_name,)).fetchall()
    return rows


def embed_and_save(conn, model, model_name, rows):
    """배치 임베딩 후 DB 저장"""
    total = len(rows)
    if total == 0:
        print("모든 소스가 이미 임베딩되어 있습니다.")
        return

    print(f"임베딩 대상: {total}건")

    source_ids = [r[0] for r in rows]
    place_ids  = [r[1] for r in rows]
    texts      = [r[2] for r in rows]

    all_embeddings = []
    for i in tqdm(range(0, total, BATCH_SIZE), desc="임베딩 중"):
        batch = texts[i:i + BATCH_SIZE]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.append(vecs)

    all_embeddings = np.vstack(all_embeddings).astype(np.float32)

    # DB 저장
    print("DB 저장 중...")
    conn.executemany(
        "INSERT OR REPLACE INTO embeddings (source_id, place_id, model_name, embedding) VALUES (?, ?, ?, ?)",
        [
            (source_ids[i], place_ids[i], model_name, all_embeddings[i].tobytes())
            for i in range(total)
        ]
    )
    conn.commit()
    print(f"DB 저장 완료: {total}건")

    return all_embeddings, source_ids, place_ids


def build_faiss_index(conn, model_name):
    """DB의 모든 임베딩으로 FAISS 인덱스 생성"""
    try:
        import faiss
    except ImportError:
        print("faiss 미설치 — FAISS 인덱스 생략 (pip install faiss-cpu)")
        return

    print("FAISS 인덱스 빌드 중...")
    rows = conn.execute("""
        SELECT e.source_id, e.place_id, e.embedding, p.name, p.district
        FROM embeddings e
        JOIN places p ON e.place_id = p.place_id
        WHERE e.model_name = ?
        ORDER BY e.source_id
    """, (model_name,)).fetchall()

    if not rows:
        print("임베딩 데이터 없음")
        return

    source_ids = [r[0] for r in rows]
    place_ids  = [r[1] for r in rows]
    names      = [r[3] for r in rows]
    districts  = [r[4] for r in rows]

    embeddings = np.array([
        np.frombuffer(r[2], dtype=np.float32) for r in rows
    ])

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)   # 내적 = cosine similarity (normalized vectors)
    index.add(embeddings)

    faiss.write_index(index, str(FAISS_INDEX_PATH))

    meta = {
        "source_ids": source_ids,
        "place_ids":  place_ids,
        "names":      names,
        "districts":  districts,
        "model_name": model_name,
        "dim":        dim,
        "total":      len(rows),
    }
    with open(META_PATH, "wb") as f:
        pickle.dump(meta, f)

    print(f"FAISS 인덱스 저장: {FAISS_INDEX_PATH} ({len(rows)}개 벡터, dim={dim})")


def search(query: str, top_k: int = 10):
    """저장된 FAISS 인덱스로 유사 장소 검색 (검증용)"""
    import faiss
    from sentence_transformers import SentenceTransformer

    with open(META_PATH, "rb") as f:
        meta = pickle.load(f)

    model = SentenceTransformer(meta["model_name"])
    index = faiss.read_index(str(FAISS_INDEX_PATH))

    vec = model.encode([query], normalize_embeddings=True).astype(np.float32)
    scores, idxs = index.search(vec, top_k)

    print(f"\n쿼리: '{query}' 유사 장소 Top-{top_k}")
    print("-" * 60)
    for rank, (idx, score) in enumerate(zip(idxs[0], scores[0]), 1):
        name     = meta["names"][idx] or "(없음)"
        district = meta["districts"][idx] or ""
        sid      = meta["source_ids"][idx]
        print(f"{rank:2}. [{score:.4f}] {name} ({district})  source_id={sid}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="sources 임베딩 파이프라인")
    parser.add_argument("--search", type=str, help="검색 쿼리 (임베딩 생성 없이 검색만)")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rebuild-index", action="store_true", help="임베딩 재사용, FAISS만 재빌드")
    args = parser.parse_args()

    if args.search:
        search(args.search, args.top_k)
        return

    conn = get_conn()
    ensure_embeddings_table(conn)

    if args.rebuild_index:
        # 모델 이름 확인
        row = conn.execute("SELECT model_name FROM embeddings LIMIT 1").fetchone()
        model_name = row[0] if row else MODEL_NAME
        build_faiss_index(conn, model_name)
        conn.close()
        return

    model, model_name = load_model()
    print(f"사용 모델: {model_name}")
    print(f"임베딩 차원: {model.get_sentence_embedding_dimension()}")

    rows = fetch_unembedded_sources(conn, model_name)
    if rows:
        embed_and_save(conn, model, model_name, rows)
    else:
        print("새로 임베딩할 소스 없음 — FAISS 인덱스만 재빌드합니다.")

    build_faiss_index(conn, model_name)
    conn.close()
    print("\n완료!")


if __name__ == "__main__":
    main()
