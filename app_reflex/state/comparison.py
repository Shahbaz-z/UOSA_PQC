"""Side-by-Side Comparison state management."""

from __future__ import annotations

from typing import List, Dict, Any
import reflex as rx

from pqc_lib.signatures import sign_keygen, sign, verify, SIG_ALGORITHMS
from pqc_lib.mock import ED25519_PARAMS


class ComparisonState(rx.State):
    """State for Side-by-Side Comparison tab."""

    # Selected algorithms
    selected_algos: List[str] = ["Ed25519", "ML-DSA-65", "Falcon-512"]

    # Test message
    compare_msg: str = "Blockchain quantum resistance test message"

    # Results storage
    compare_results: Dict[str, Dict[str, Any]] = {}

    # Running state
    is_running: bool = False
    progress: float = 0.0
    current_algo: str = ""

    def set_compare_msg(self, value: str):
        """Set the comparison message."""
        self.compare_msg = value

    def toggle_algorithm(self, algo: str):
        """Toggle algorithm selection."""
        if algo in self.selected_algos:
            if len(self.selected_algos) > 1:  # Keep at least one
                self.selected_algos = [a for a in self.selected_algos if a != algo]
        else:
            self.selected_algos = self.selected_algos + [algo]

    def select_all_pqc(self):
        """Select all PQC algorithms."""
        pqc_algos = [a for a in SIG_ALGORITHMS if not a.startswith("Hybrid") and a not in ("Ed25519",)]
        self.selected_algos = ["Ed25519"] + pqc_algos[:5]  # Limit for performance

    def select_minimal(self):
        """Select minimal comparison set."""
        self.selected_algos = ["Ed25519", "ML-DSA-65", "Falcon-512"]

    def select_lattice_based(self):
        """Select lattice-based algorithms."""
        self.selected_algos = ["Ed25519", "ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "Falcon-512"]

    async def run_comparison(self):
        """Run comparison asynchronously with progress updates."""
        if len(self.selected_algos) < 2:
            return

        self.is_running = True
        self.compare_results = {}
        self.progress = 0.0
        message = self.compare_msg.encode()

        total = len(self.selected_algos)

        for i, algo in enumerate(self.selected_algos):
            self.current_algo = algo
            self.progress = (i / total) * 100
            yield  # Update UI

            # Run cryptographic operations
            kp = sign_keygen(algo)
            sr = sign(algo, kp.secret_key, message, kp)
            vr = verify(algo, kp.public_key, message, sr.signature, kp)

            self.compare_results[algo] = {
                "pk_size": len(kp.public_key),
                "sk_size": len(kp.secret_key),
                "sig_size": sr.signature_size,
                "keygen_ms": round(kp.keygen_time_ms, 3),
                "sign_ms": round(sr.time_ms, 3),
                "verify_ms": round(vr.time_ms, 3),
                "valid": vr.valid,
                "vs_ed25519": round(sr.signature_size / ED25519_PARAMS["signature"], 1),
            }

        self.progress = 100
        self.is_running = False
        self.current_algo = ""

    # --- Computed Properties ---

    @rx.var
    def available_algorithms(self) -> List[str]:
        """Get list of available signature algorithms."""
        # Filter out hybrid for simplicity
        return [a for a in SIG_ALGORITHMS if not a.startswith("Hybrid")]

    @rx.var
    def enough_selected(self) -> bool:
        """Check if enough algorithms are selected."""
        return len(self.selected_algos) >= 2

    @rx.var
    def has_results(self) -> bool:
        """Check if results are available."""
        return len(self.compare_results) > 0

    @rx.var
    def results_list(self) -> List[Dict[str, Any]]:
        """Get results as a list for display."""
        return [
            {"algorithm": algo, **data}
            for algo, data in self.compare_results.items()
        ]

    @rx.var
    def smallest_signature(self) -> str:
        """Get algorithm with smallest signature."""
        if not self.compare_results:
            return "N/A"
        return min(self.compare_results.items(), key=lambda x: x[1]["sig_size"])[0]

    @rx.var
    def fastest_sign(self) -> str:
        """Get algorithm with fastest signing."""
        if not self.compare_results:
            return "N/A"
        return min(self.compare_results.items(), key=lambda x: x[1]["sign_ms"])[0]

    @rx.var
    def fastest_verify(self) -> str:
        """Get algorithm with fastest verification."""
        if not self.compare_results:
            return "N/A"
        return min(self.compare_results.items(), key=lambda x: x[1]["verify_ms"])[0]

    @rx.var
    def chart_data(self) -> Dict[str, List]:
        """Get data formatted for charts."""
        if not self.compare_results:
            return {"algorithms": [], "sig_sizes": [], "sign_times": []}

        algos = list(self.compare_results.keys())
        return {
            "algorithms": algos,
            "sig_sizes": [self.compare_results[a]["sig_size"] for a in algos],
            "sign_times": [self.compare_results[a]["sign_ms"] for a in algos],
        }
