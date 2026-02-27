"""Node class with SimPy Resource-based bandwidth and CPU contention.

CRITICAL DESIGN DECISIONS (per Quant Lead review):

1. BANDWIDTH CONTENTION:
   - Each node has a SimPy Resource representing upload bandwidth.
   - Only one block can be transmitted at a time per node (single-lane model).
   - Transmission time = block_size / upload_bandwidth.
   - Queue forms automatically when multiple blocks compete.

2. CPU CONTENTION:
   - Each node has a SimPy Resource representing CPU cores.
   - Signature verification consumes CPU for the duration of verification.
   - Verification time derived from analytical queuing model (M/M/c):
     * arrival_rate estimated from current block rate and tx count
     * service_rate from per-signature verification time
     * c = num_cpu_cores
   - Heavy PQC signatures cause realistic CPU saturation.

3. QUEUING DELAYS:
   - Both bandwidth and CPU queuing use SimPy Resources.
   - Queuing delay = time waiting for resource to become available.
   - This naturally models contention without artificial limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
import simpy

from blockchain.verification import (
    get_verification_time,
    get_verification_time_mmc,
)

logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """Configuration for a network node."""

    node_id: str
    node_type: str                  # "validator" or "full_node"
    region: str
    upload_bandwidth_mbps: float
    download_bandwidth_mbps: float
    cpu_cores: int
    signature_algorithm: str
    is_pqc: bool = False


class Node:
    """Network node with bandwidth and CPU contention modeling."""

    def __init__(self, env: simpy.Environment, config: NodeConfig):
        self.env = env
        self.config = config
        # Bandwidth resource: 1 slot = one active transmission
        self._bw_resource = simpy.Resource(env, capacity=1)
        # CPU resource: capacity = number of cores
        self._cpu_resource = simpy.Resource(env, capacity=config.cpu_cores)
        self._blocks_verified = 0
        self._total_verify_time = 0.0
        # Track recent block arrival times for M/M/c arrival rate estimation
        self._recent_arrivals: list = []

    def get_bandwidth_queue_delay(self, size_bytes: int) -> float:
        """Return estimated queuing delay for bandwidth resource.

        Uses current queue length to estimate wait time.
        """
        queue_len = len(self._bw_resource.queue)
        if queue_len == 0:
            return 0.0
        # Estimate: each queued request takes ~size_bytes / bandwidth
        bps = self.config.upload_bandwidth_mbps * 1e6 / 8
        return queue_len * size_bytes / bps

    def schedule_verification(self, block):
        """Schedule block verification using analytical M/M/c queuing model.

        FIX #2: Uses get_verification_time_mmc() (analytical CPU queuing model)
        instead of the old fixed per-signature lookup. This properly accounts
        for CPU core count, current queue depth, and realistic arrival rates.
        """
        with self._cpu_resource.request() as req:
            yield req

            # Track arrival for rate estimation
            now = self.env.now
            self._recent_arrivals.append(now)
            # Keep only last 20 arrivals for rate estimation
            if len(self._recent_arrivals) > 20:
                self._recent_arrivals = self._recent_arrivals[-20:]

            # Estimate arrival rate from recent history
            if len(self._recent_arrivals) >= 2:
                window = self._recent_arrivals[-1] - self._recent_arrivals[0]
                arrival_rate = (len(self._recent_arrivals) - 1) / window if window > 0 else 1.0
            else:
                arrival_rate = 1.0  # default: 1 block/s

            num_sigs = len(block.transactions)

            # FIX #2: Use analytical M/M/c queuing model
            verify_time = get_verification_time_mmc(
                algorithm=self.config.signature_algorithm,
                num_signatures=num_sigs,
                num_cores=self.config.cpu_cores,
                arrival_rate=arrival_rate,
            )

            yield self.env.timeout(verify_time)
            self._blocks_verified += 1
            self._total_verify_time += verify_time
            return verify_time

    def get_avg_verify_time(self) -> float:
        """Return average verification time per block."""
        if self._blocks_verified == 0:
            return 0.0
        return self._total_verify_time / self._blocks_verified
