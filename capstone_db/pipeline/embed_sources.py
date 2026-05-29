"""
Phase 3.5 — places 임베딩 생성
places.sources JSON → 텍스트 합치기 → sentence-transformers → places.embedding (BLOB)
+ FAISS 인덱스 생성

모델: jhgan/ko-sroberta-multitask (한국어 특화)
      fallback: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
"""

import sqlite3
import json
import numpy as np
import pickle
from pathlib import Path
from tqdm import tqdm

DB_PATH = Path("/Users/minhee/Desktop/DB/capstone_db/seoul_docent.db")
FAISS_INDEX_PATH = DB_PATH.parent / "faiss_index.bin"
META_PATH = DB_PATH.parent / "faiss_meta.pkl"

MODEL_NAME = "jhgan/ko-sroberta-multitask"
FALLBACK_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

BATCH_SIZE = 64
MAX_TEXT_LEN = 1000  # 장소당 텍스트 최대 길이 (토큰 제한 대비)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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


def extract_text(name, sources_json):
    """places.sources JSON에서 모든 출처 텍스트를 합쳐 반환"""
    parts = [name or ""]
    if sources_json:
        try:
            src = json.loads(sources_json)
            for v in src.values():
                if v and isinstance(v, str):
                    parts.append(v[:MAX_TEXT_LEN])
        except Exception:
            pass
    return " ".join(parts).strip()


def fetch_unembedded(conn):
    """임베딩이 없는 장소만 반환"""
    rows = conn.execute("""
        SELECT place_id, name, sources
        FROM places
        WHERE embedding IS NULL
          AND (sources IS NOT NULL OR name IS NOT NULL)
    """).fetchall()
    return rows


def embed_and_save(conn, model, model_name, rows):
    total = len(rows)
    if total == 0:
        print("모든 장소가 이미 임베딩되어 있습니다.")
        return

    print(f"임베딩 대상: {total}건")

    place_ids = [r[0] for r in rows]
    texts = [extract_text(r[1], r[2]) for r in rows]

    all_embeddings = []
    for i in tqdm(range(0, total, BATCH_SIZE), desc="임베딩 중"):
        batch = texts[i:i + BATCH_SIZE]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.append(vecs)

    all_embeddings = np.vstack(all_embeddings).astype(np.float32)

    print("DB 저장 중...")
    conn.executemany(
        "UPDATE places SET embedding = ? WHERE place_id = ?",
        [
            (all_embeddings[i].tobytes(), place_ids[i])
            for i in range(total)
        ]
    )
    conn.commit()
    print(f"DB 저장 완료: {total}건")

    return all_embeddings, place_ids


def build_faiss_index(conn):
    """places.embedding으로 FAISS 인덱스 생성"""
    try:
        import faiss
    except ImportError:
        print("faiss 미설치 — FAISS 인덱스 생략 (pip install faiss-cpu)")
        return

    print("FAISS 인덱스 빌드 중...")
    rows = conn.execute("""
        SELECT place_id, name, embedding
        FROM places
        WHERE embedding IS NOT NULL
        ORDER BY place_id
    """).fetchall()

    if not rows:
        print("임베딩 데이터 없음")
        return

    place_ids = [r[0] for r in rows]
    names = [r[1] for r in rows]
    embeddings = np.array([
        np.frombuffer(r[2], dtype=np.float32) for r in rows
    ])

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, str(FAISS_INDEX_PATH))

    meta = {
        "place_ids": place_ids,
        "names": names,
        "model_name": MODEL_NAME,
        "dim": dim,
        "total": len(rows),
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
        name = meta["names"][idx] or "(없음)"
        pid = meta["place_ids"][idx]
        print(f"{rank:2}. [{score:.4f}] {name}  place_id={pid}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="places 임베딩 파이프라인")
    parser.add_argument("--search", type=str, help="검색 쿼리 (임베딩 없이 검색만)")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rebuild-index", action="store_true", help="임베딩 재사용, FAISS만 재빌드")
    args = parser.parse_args()

    if args.search:
        search(args.search, args.top_k)
        return

    conn = get_conn()

    if args.rebuild_index:
        build_faiss_index(conn)
        conn.close()
        return

    model, model_name = load_model()
    print(f"사용 모델: {model_name}")
    print(f"임베딩 차원: {model.get_sentence_embedding_dimension()}")

    rows = fetch_unembedded(conn)
    if rows:
        embed_and_save(conn, model, model_name, rows)
    else:
        print("새로 임베딩할 장소 없음 — FAISS 인덱스만 재빌드합니다.")

    build_faiss_index(conn)
    conn.close()
    print("\n완료!")


if __name__ == "__main__":
    main()
