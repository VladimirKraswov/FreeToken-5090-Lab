# Hardware and runtime, 2026-09-21

| Component | Measured configuration |
|---|---|
| Hypervisor | Proxmox VE 9.1.11, kernel 7.0.2-2-pve |
| Motherboard / BIOS | Lenovo RD450X / R450X231 |
| Host CPU | 2 x Intel Xeon E5-2698 v4, 20 cores/socket, 40 cores / 80 SMT threads total |
| Host RAM | 15 x 32 GB DIMMs = 480 GiB nominal, about 472 GiB OS-visible; DDR4 at 2133 MT/s |
| Host CPU governor | performance, intel_cpufreq |
| NUMA | Two nodes; GPU local to NUMA node 0 |
| GPU | NVIDIA GeForce RTX 5090; 32607 MiB NVML total, 495 MiB driver-reserved |
| GPU limit | 500 W, persistent service reapplies on boot |
| PCIe | Gen3 x16 under load, 12.57 GB/s measured pinned H2D; Gen1 at idle is normal power management |
| VM allocation | 32 vCPU, 160 GiB fixed RAM, 400 GiB virtual SSD; ballooning off |
| CPU placement | Host CPUs 0-15,40-55: 16 physical cores plus SMT, common affinity mask; not 32 dedicated physical cores |
| Guest NUMA | One virtual NUMA node, memory strictly bound to host NUMA0; CPU type host |
| VM firmware/disk | q35, OVMF, virtio-scsi-single, IO thread, cache=none, discard, SSD flag |
| Backing SSD | ADATA LEGEND 900, 2 TB, LVM-thin; model and guest OS on this storage |
| Other host SSDs | Samsung 980 PRO 1 TB (hypervisor), ADATA LEGEND 710 1 TB; not additional model-memory tiers |
| Guest OS | Ubuntu 24.04.5 LTS, kernel 6.8.0-139-generic |
| NVIDIA driver | 595.91.07 |
| CUDA toolkit used to build | 13.3.73 |
| PyTorch | 2.11.0+cu130; its bundled CUDA runtime reports 13.0, distinct from the toolkit/driver capability |
| Transformers | 5.16.1; Python 3.12 |

The alternative media VM is stopped while the LLM VM owns the GPU. The card is
exclusive PCIe passthrough, not simultaneously shared. V100 and temporary 3090
nodes do not contribute to these measurements. Existing unrelated host guests
remained present; this is not a bare-metal benchmark.

The final GPU worker RSS was about 117 GiB, plus about 0.85 GiB for the API
supervisor, including the resident expert banks and 47.7 GiB pinned PLE table.
Earlier warm observations reached about 122 GiB. The inference processes, guest
and its QEMU process had no swapped pages at their recorded checks. The host
as a whole had about 1.7 GiB swap usage from other workloads; claiming that the
entire host never swapped would be incorrect. QEMU's roughly 160 GiB RSS was
backed by hugepages (observed through AnonHugePages).

The final post-validation NVML reading was 31850 MiB used and 262 MiB free
(earlier pre-audit: 31814 MiB used and 298 MiB free). This includes
PyTorch allocator reservations and is not all active model tensors. Memory ratio
0.87 is a planner input, not a promise of 13% free memory after graphs and JIT.
This profile deliberately runs close to capacity; higher concurrent request
counts or larger image limits were not validated.

## Bandwidth calibration

`ft bench bw` on the actual guest/GPU, 2026-09-21:

| Measurement | GB/s |
|---|---:|
| CPU streaming reads | 57.47 |
| Linear pinned H2D | 12.57 |
| Linear D2H | 10.56 |
| NVFP4 CPU expert computation, AVX2 | 33.66 |
| PCIe expert gather | 11.06 |
| Contended CPU lane | 17.62 |
| Contended PCIe lane | 10.67 |

The resulting hybrid policy fetches about 37.7% of misses and computes the rest
on CPU. A bandwidth recommendation alone did not select the winning serving
profile: full-request measurements did. Twelve CPU expert workers leave room
for routing, scheduling and transfers within the sixteen physical cores.
