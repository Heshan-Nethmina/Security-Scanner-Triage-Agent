# Container image for the Security Scanner Triage Agent dashboard.
#
#   docker build -t triage-agent .
#   docker run --rm -e GROQ_API_KEY=your-key -p 8501:8501 triage-agent
#   # then open http://localhost:8501
FROM python:3.13-slim

WORKDIR /app

# onnxruntime (Chroma's built-in embedder) needs libgomp at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the RAG store into the image (downloads the embedding model once;
# no API key needed for indexing).
RUN python -m app.rag.knowledge_base

EXPOSE 8501
# The GROQ_API_KEY is provided at run time via -e, never baked into the image.
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501"]
