FROM python:3.11-slim

# Install build dependencies for liboqs
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake ninja-build gcc g++ \
    libssl-dev git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Build and install liboqs (pinned to 0.12.0 to match liboqs-python==0.12.0)
RUN git clone --depth 1 --branch 0.12.0 \
        https://github.com/open-quantum-safe/liboqs.git /tmp/liboqs \
    && cd /tmp/liboqs \
    && mkdir build && cd build \
    && cmake -GNinja \
        -DBUILD_SHARED_LIBS=ON \
        -DOQS_BUILD_ONLY_LIB=ON \
        .. \
    && ninja && ninja install \
    && ldconfig \
    && rm -rf /tmp/liboqs

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Streamlit config
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app/pqc_demo_streamlit.py"]
