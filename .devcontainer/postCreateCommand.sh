#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing build dependencies ==="
sudo apt-get update
sudo apt-get install -y cmake ninja-build gcc g++ libssl-dev

echo "=== Building liboqs C library ==="
git clone --depth 1 --branch 0.12.0 https://github.com/open-quantum-safe/liboqs.git /tmp/liboqs
cmake -S /tmp/liboqs -B /tmp/liboqs/build -G Ninja \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBUILD_SHARED_LIBS=ON
ninja -C /tmp/liboqs/build
sudo ninja -C /tmp/liboqs/build install
sudo ldconfig
rm -rf /tmp/liboqs

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Verifying liboqs ==="
python -c "import oqs; print('liboqs OK:', oqs.get_enabled_kem_mechanisms()[:3])"

echo "=== Setup complete ==="
