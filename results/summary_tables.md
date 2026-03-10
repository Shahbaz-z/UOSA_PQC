# PQC Impact Analysis — Summary Tables

## Bitcoin: Block Capacity Under PQC

| Algorithm | Security | Sig (B) | PK (B) | Tx Weight | Txs/Block | TPS | Throughput Reduction |
|-----------|----------|---------|--------|-----------|-----------|-----|---------------------|
| ECDSA (secp256k1) | ~128-bit | 72 | 33 | 854 | 4,683 | 7.80 | 0.0% |
| FALCON-512 | NIST-1 | 666 | 897 | 3,770 | 1,061 | 1.77 | 77.3% |
| FALCON-1024 | NIST-5 | 1,280 | 1,793 | 6,790 | 589 | 0.98 | 87.4% |
| Dilithium2 (ML-DSA-44) | NIST-2 | 2,420 | 1,312 | 8,108 | 493 | 0.82 | 89.5% |
| Dilithium3 (ML-DSA-65) | NIST-3 | 3,293 | 1,952 | 11,134 | 359 | 0.60 | 92.3% |
| Dilithium5 (ML-DSA-87) | NIST-5 | 4,595 | 2,592 | 15,018 | 266 | 0.44 | 94.3% |
| SPHINCS+-128s | NIST-1 | 7,856 | 32 | 16,420 | 243 | 0.41 | 94.8% |
| SPHINCS+-256s | NIST-5 | 29,792 | 64 | 60,356 | 66 | 0.11 | 98.6% |

## Bitcoin: Fee Market Impact (50% PQC, Medium Pressure)

| Algorithm | Txs Included | Revenue (sat) | ECDSA Incl. | PQC Incl. | Fee Premium | PQC Stuck |
|-----------|-------------|---------------|-------------|-----------|-------------|-----------|
| FALCON-512 | 1,723 | 82,092,040 | 12.3% | 12.2% | +1.4% | 6,253 |
| FALCON-1024 | 1,034 | 98,419,999 | 7.3% | 7.4% | -1.0% | 6,595 |
| Dilithium2 (ML-DSA-44) | 886 | 103,908,767 | 6.3% | 6.3% | +1.1% | 6,673 |
| Dilithium3 (ML-DSA-65) | 663 | 113,961,802 | 4.8% | 4.7% | +0.0% | 6,786 |
| Dilithium5 (ML-DSA-87) | 504 | 124,165,663 | 3.6% | 3.5% | -0.3% | 6,868 |
| SPHINCS+-128s | 473 | 127,377,833 | 3.5% | 3.2% | +2.2% | 6,889 |
| SPHINCS+-256s | 155 | 180,454,329 | 1.3% | 0.9% | +7.3% | 7,055 |

## Ethereum: Gas Cost Analysis

| Algorithm | Security | Verify Gas | Overhead | Simple TPS | ERC-20 TPS | Reduction |
|-----------|----------|------------|----------|------------|------------|-----------|
| ECDSA (secp256k1) | ~128-bit | 3,000 | +0 | 97.5 | 35.8 | 0.0% |
| FALCON-512 | NIST-1 | 10,000 | +29,452 | 45.3 | 25.2 | 53.5% |
| FALCON-1024 | NIST-5 | 18,000 | +60,712 | 28.9 | 19.2 | 70.3% |
| Dilithium2 (ML-DSA-44) | NIST-2 | 15,000 | +67,860 | 26.7 | 18.2 | 72.7% |
| Dilithium3 (ML-DSA-65) | NIST-3 | 22,000 | +98,156 | 20.2 | 14.8 | 79.3% |
| Dilithium5 (ML-DSA-87) | NIST-5 | 35,000 | +141,064 | 14.9 | 11.8 | 84.7% |
| SPHINCS+-128s | NIST-1 | 100,000 | +216,860 | 10.2 | 8.7 | 89.5% |
| SPHINCS+-256s | NIST-5 | 300,000 | +755,172 | 3.2 | 3.0 | 96.8% |

## Ethereum: EIP-1559 Base Fee Impact

| Algorithm | Equilibrium Fee (gwei) | Multiplier | Avg Utilization | Blocks > Target |
|-----------|------------------------|------------|-----------------|-----------------|
| ECDSA (secp256k1) | 1.00 | 1.00x | 12.8% | 0/1000 |
| FALCON-512 | 1.00 | 1.00x | 27.5% | 0/1000 |
| FALCON-1024 | 1.00 | 1.00x | 43.2% | 0/1000 |
| Dilithium2 (ML-DSA-44) | 1.00 | 1.00x | 46.7% | 0/1000 |
| Dilithium3 (ML-DSA-65) | 37.75 | 37.75x | 50.1% | 216/1000 |
| Dilithium5 (ML-DSA-87) | 58.12 | 58.12x | 50.3% | 1000/1000 |
| SPHINCS+-128s | 123.94 | 123.94x | 50.6% | 888/1000 |
| SPHINCS+-256s | 19991.54 | 19991.54x | 52.7% | 362/1000 |

## Ethereum: Consensus Layer Impact

| Algorithm | Attestation Size | Multiplier | BW Required (Mbps) | Feasible? | Overhead (KB) |
|-----------|------------------|------------|--------------------|-----------|--------------:|
| ECDSA (secp256k1) | 224 B | 1.0x | 0.0 | ✓ | 0.0 |
| FALCON-512 | 406,528 B | 1814.9x | 52.0 | ✓ | 25,394.0 |
| FALCON-1024 | 720,896 B | 3218.3x | 92.3 | ✓ | 45,042.0 |
| Dilithium2 (ML-DSA-44) | 1,304,576 B | 5824.0x | 167.0 | ✗ | 81,522.0 |
| Dilithium3 (ML-DSA-65) | 1,751,552 B | 7819.4x | 224.2 | ✗ | 109,458.0 |
| Dilithium5 (ML-DSA-87) | 2,418,176 B | 10795.4x | 309.5 | ✗ | 151,122.0 |
| SPHINCS+-128s | 4,087,808 B | 18249.1x | 523.2 | ✗ | 255,474.0 |
| SPHINCS+-256s | 15,319,040 B | 68388.6x | 1,960.8 | ✗ | 957,426.0 |

## Migration Thresholds

### Bitcoin

| Algorithm | 50% TPS Drop At | Fee 2× Premium At |
|-----------|-----------------|-------------------|
| FALCON-512 | 35% | N/A |
| FALCON-1024 | 15% | N/A |
| Dilithium2 (ML-DSA-44) | 15% | N/A |
| Dilithium3 (ML-DSA-65) | 10% | N/A |
| Dilithium5 (ML-DSA-87) | 10% | N/A |
| SPHINCS+-128s | 5% | N/A |
| SPHINCS+-256s | 5% | N/A |

### Ethereum

| Algorithm | Gas Limit Increase At | Consensus Feasible? |
|-----------|----------------------|---------------------|
| FALCON-512 | 50% | ✓ |
| FALCON-1024 | 25% | ✓ |
| Dilithium2 (ML-DSA-44) | 25% | ✗ |
| Dilithium3 (ML-DSA-65) | 15% | ✗ |
| Dilithium5 (ML-DSA-87) | 15% | ✗ |
| SPHINCS+-128s | 10% | ✗ |
| SPHINCS+-256s | 5% | ✗ |
