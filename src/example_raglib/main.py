import spacy
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

class ExampleRAG:
    def __init__(self):
        self._nlp = spacy.load("en_core_web_md")
        self._docs = []
        self._vectors = []

    def add(self, text: str):
        vec = self._nlp(text).vector
        self._docs.append(text)
        self._vectors.append(vec)

    def add_text_file(self, path: str, chunk_size: int = 300):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        for i in range(0, len(text), chunk_size):
            self.add(text[i:i + chunk_size])

    def ask(self, query: str) -> str:
        if not self._docs:
            return "No data."

        q_vec = self._nlp(query).vector.reshape(1, -1)
        sims = cosine_similarity(self._vectors, q_vec).flatten()
        return self._docs[int(np.argmax(sims))]