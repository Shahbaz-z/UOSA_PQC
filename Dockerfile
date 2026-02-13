FROM python:3.11-slim

# Install build dependencies for liboqs
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake ninja-build gcc g++ \
    libssl-dev git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Build and install liboqs (0.14.0 to match liboqs-python 0.14.x)
RUN git clone --depth 1 --branch 0.14.0 \
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

# Reflex config
ENV REFLEX_FRONTEND_PORT=3000
ENV REFLEX_BACKEND_PORT=8000

# Streamlit config (legacy, kept for reference)
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Expose both Reflex ports and legacy Streamlit port
EXPOSE 3000 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3000 || exit 1

# Default: Run Reflex app
# To run Streamlit instead: docker run ... streamlit run app/pqc_demo_streamlit.py
CMD ["reflex", "run", "--env", "prod"]
