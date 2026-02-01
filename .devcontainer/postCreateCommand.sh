#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing build dependencies ==="
sudo apt-get update
sudo apt-get install -y cmake ninja-build gcc g++ libssl-dev git

echo "=== Building liboqs C library (v0.12.0) ==="
rm -rf /tmp/liboqs
git clone --depth 1 --branch 0.12.0 https://github.com/open-quantum-safe/liboqs.git /tmp/liboqs
cmake -S /tmp/liboqs -B /tmp/liboqs/build -G Ninja \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_SHARED_LIBS=ON
ninja -C /tmp/liboqs/build
sudo ninja -C /tmp/liboqs/build install
sudo ldconfig
rm -rf /tmp/liboqs

echo "=== Installing Python dependencies ==="
python3 -m pip install -r requirements.txt

echo "=== Verifying liboqs ==="
python3 -c "import oqs; print('liboqs OK:', oqs.get_enabled_kem_mechanisms()[:3])"

echo "=== Setup complete. Run: python3 -m streamlit run app/pqc_demo_streamlit.py ==="
