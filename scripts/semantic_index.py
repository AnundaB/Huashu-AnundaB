import os
import sys
import json
import hashlib
import datetime
import numpy as np

try:
    from turbovec import IdMapIndex
    HAS_TURBOVEC = True
except ImportError:
    HAS_TURBOVEC = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO_DIR = os.getenv("HUASHU_AUTO_DIR", os.path.join(REPO_ROOT, "outputs", "auto"))
SEMANTIC_DIR = os.path.join(AUTO_DIR, "semantic_index")
INDEX_FILE_TVIM = os.path.join(SEMANTIC_DIR, "index.tvim")
VECTORS_FILE_NPY = os.path.join(SEMANTIC_DIR, "vectors.npy")
IDS_FILE_NPY = os.path.join(SEMANTIC_DIR, "ids.npy")
METADATA_FILE = os.path.join(SEMANTIC_DIR, "metadata.json")


def text_to_vector_128(text: str) -> np.ndarray:
    """
    Deterministically embeds a text chunk into a 128-dimensional dense vector space.
    Uses MD5 hashes of individual words to seed a deterministic generator, projecting
    words onto a unit hypersphere, and aggregates/renormalizes.
    """
    words = [w.strip() for w in text.lower().split() if w.strip()]
    if not words:
        return np.zeros(128, dtype=np.float32)

    vec = np.zeros(128, dtype=np.float32)
    for word in words:
        h = hashlib.md5(word.encode("utf-8")).digest()
        seed_int = int.from_bytes(h, byteorder="big") % (2**32)
        rng = np.random.default_rng(seed_int)
        
        word_vec = rng.standard_normal(128)
        norm = np.linalg.norm(word_vec)
        if norm > 0:
            word_vec /= norm
        vec += word_vec

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32)


DEFAULT_PROVIDER_NAME = "local_projected_hash_128"
DEFAULT_MODEL_ID = "projected_hash_128"
DEFAULT_DIMENSION = 128
CHUNKER_VERSION = "1.0.0"
INDEX_SCHEMA_VERSION = "1.0.0"


class SemanticIndex:
    def __init__(
        self,
        provider_name: str = DEFAULT_PROVIDER_NAME,
        model_id: str = DEFAULT_MODEL_ID,
        dimension: int = DEFAULT_DIMENSION
    ):
        self.provider_name = provider_name
        self.model_id = model_id
        self.dimension = dimension
        self.chunker_version = CHUNKER_VERSION
        self.index_schema_version = INDEX_SCHEMA_VERSION

        self.metadata = {}  # maps integer ID (str) to document details
        self.vectors = []
        self.ids = []
        self.id_counter = 1
        self.load()

    def _embed(self, text: str) -> np.ndarray:
        if self.provider_name == DEFAULT_PROVIDER_NAME:
            return text_to_vector_128(text)
        else:
            raise NotImplementedError(f"Embedding provider {self.provider_name} not implemented in Phase 1.")

    @property
    def source_file_hash(self) -> str:
        # Combine hashes of all documents in deterministic alphabetical document order.
        # This must not depend on insertion order or internal integer IDs.
        combined = []
        docs = sorted(
            self.metadata.values(),
            key=lambda doc: (doc.get("document_id", ""), doc.get("file_hash", "")),
        )
        for doc_info in docs:
            doc_id = doc_info.get("document_id", "")
            file_hash = doc_info.get("file_hash", "")
            combined.append(f"{doc_id}:{file_hash}")
        return hashlib.md5("\n".join(combined).encode("utf-8")).hexdigest()

    def load(self):
        """Loads index and metadata from disk if present."""
        if not os.path.exists(METADATA_FILE):
            return
        
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            index_metadata = data.get("index_metadata", {})
            
            # Fail closed if stored dimension/model/provider mismatches runtime.
            stored_provider = index_metadata.get("provider_name")
            stored_model = index_metadata.get("model_id")
            stored_dim = index_metadata.get("dimension")
            
            if stored_provider is not None and stored_provider != self.provider_name:
                raise ValueError(f"Provider mismatch: expected {self.provider_name}, got {stored_provider}")
            if stored_model is not None and stored_model != self.model_id:
                raise ValueError(f"Model ID mismatch: expected {self.model_id}, got {stored_model}")
            if stored_dim is not None and stored_dim != self.dimension:
                raise ValueError(f"Dimension mismatch: expected {self.dimension}, got {stored_dim}")
            
            self.metadata = data.get("metadata", {})
            self.id_counter = data.get("id_counter", 1)
            self.ids = data.get("ids", [])
                
            if os.path.exists(VECTORS_FILE_NPY):
                self.vectors = np.load(VECTORS_FILE_NPY).tolist()
                
            # Fail closed if len(ids) != vectors.shape[0]
            vectors_arr = np.array(self.vectors, dtype=np.float32)
            if len(self.ids) > 0 and len(self.ids) != vectors_arr.shape[0]:
                raise ValueError(f"Index corruption: len(ids)={len(self.ids)} does not match vectors.shape[0]={vectors_arr.shape[0]}")
                
            # Check vector dimensions
            if len(self.vectors) > 0:
                first_vector_dim = len(self.vectors[0])
                if first_vector_dim != self.dimension:
                    raise ValueError(f"Dimension mismatch in loaded vectors: expected {self.dimension}, got {first_vector_dim}")
        except Exception as e:
            print(f"[error] Failed to load semantic index (failing closed): {e}")
            raise e

    def save(self):
        """Saves index and metadata to disk."""
        os.makedirs(SEMANTIC_DIR, exist_ok=True)
        try:
            # Check for mismatches before saving
            if len(self.ids) > 0:
                vectors_arr = np.array(self.vectors, dtype=np.float32)
                ids_arr = np.array(self.ids, dtype=np.uint64)
                
                if len(self.ids) != vectors_arr.shape[0]:
                    raise ValueError(f"Index corruption before saving: len(ids)={len(self.ids)} != vectors.shape[0]={vectors_arr.shape[0]}")
                
                # Check vector dimensions
                if vectors_arr.shape[1] != self.dimension:
                    raise ValueError(f"Dimension mismatch before saving: expected {self.dimension}, got {vectors_arr.shape[1]}")
            
            # Construct the index-level metadata
            index_meta = {
                "provider_name": self.provider_name,
                "model_id": self.model_id,
                "dimension": self.dimension,
                "chunker_version": self.chunker_version,
                "index_schema_version": self.index_schema_version,
                "source_file_hash": self.source_file_hash
            }

            with open(METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "index_metadata": index_meta,
                    "metadata": self.metadata,
                    "id_counter": self.id_counter,
                    "ids": self.ids
                }, f, ensure_ascii=False, indent=2)

            if len(self.ids) > 0:
                # Always save numpy files so we can reload the vectors to rebuild/append
                np.save(VECTORS_FILE_NPY, vectors_arr)
                np.save(IDS_FILE_NPY, ids_arr)

                if HAS_TURBOVEC:
                    index = IdMapIndex(dim=self.dimension, bit_width=4)
                    index.add_with_ids(vectors_arr, ids_arr)
                    index.write(INDEX_FILE_TVIM)
        except Exception as e:
            print(f"[error] Failed to save semantic index: {e}")
            raise e

    def add_document(self, document_id: str, text: str):
        """Embeds text and adds it to the index."""
        vector = self._embed(text).tolist()
        
        # Check vector dimension to prevent mixing different dimensions
        if len(vector) != self.dimension:
            raise ValueError(f"Vector dimension mismatch: expected {self.dimension}, got {len(vector)}")
            
        file_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        
        # Check if already exists in metadata to update
        existing_id = None
        for int_id, doc in self.metadata.items():
            if doc["document_id"] == document_id:
                existing_id = int(int_id)
                break

        if existing_id is not None:
            idx = self.ids.index(existing_id)
            self.vectors[idx] = vector
            self.metadata[str(existing_id)] = {
                "document_id": document_id,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_hash": file_hash
            }
        else:
            new_id = self.id_counter
            self.id_counter += 1
            self.ids.append(new_id)
            self.vectors.append(vector)
            self.metadata[str(new_id)] = {
                "document_id": document_id,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_hash": file_hash
            }
        
        self.save()

    def search_similar(self, query_text: str, k: int = 5) -> list[tuple[str, float]]:
        """Searches similar documents in the index."""
        if not self.ids:
            return []

        query_vec = self._embed(query_text)
        
        if len(query_vec) != self.dimension:
            raise ValueError(f"Query vector dimension mismatch: expected {self.dimension}, got {len(query_vec)}")
            
        k = min(k, len(self.ids))

        if HAS_TURBOVEC and os.path.exists(INDEX_FILE_TVIM):
            try:
                index = IdMapIndex.load(INDEX_FILE_TVIM)
                scores, ids = index.search(query_vec.reshape(1, -1), k=k)
                scores = scores[0].tolist()
                ids = ids[0].tolist()
                results = []
                for score, doc_id in zip(scores, ids):
                    doc = self.metadata.get(str(doc_id))
                    if doc:
                        results.append((doc["document_id"], float(score)))
                return results
            except Exception as e:
                print(f"[warn] turbovec search failed: {e}. Falling back to NumPy.")

        # NumPy fallback
        vectors_arr = np.array(self.vectors, dtype=np.float32)
        scores = np.dot(vectors_arr, query_vec)
        top_indices = np.argsort(scores)[::-1][:k]
        
        results = []
        for idx in top_indices:
            doc_id = self.ids[idx]
            doc = self.metadata.get(str(doc_id))
            if doc:
                results.append((doc["document_id"], float(scores[idx])))
        return results
