## 7.3.1 Real-carbon topology sweep

To check whether the topology-sensitivity findings of §7.3 are
artefacts of synthetic carbon amplitudes, we re-ran the same five
topologies with the real LWA 2020 carbon traces (DE, FR, GB, US-CAISO)
plus a calibrated PL trace (LWA-documented mean of 791 g CO2eq/kWh,
coal-base-load diurnal shape; see `scripts/generate_pl_trace.py`). The
workload is the same schema-correct synthetic stream as §7.3 since the
Azure 2019 and 2021 traces are not directly fetchable from our build
environment.

Three findings emerge.

**Finding 1: GreenFaaS matches Spatial within 1.3pp on real data
across all topologies.** Real data:

| Topology              | Spatial   | GreenFaaS | gap   |
|-----------------------|----------:|----------:|------:|
| Full 5-region         | --76.2%   | --75.8%   | --0.4 |
| EU-only (FR/DE/GB/PL) | --81.9%   | --81.5%   | --0.3 |
| Coal-belt (DE/GB/PL)  | --43.0%   | --41.8%   | --1.3 |
| Single-region DE      |   0.0%    |   0.0%    |   0.0 |
| Single-region CAISO   |   0.0%    |   0.0%    |   0.0 |

The headline 76--79% reduction from §7.2 holds (75--82% on real
multi-region topologies); the GreenFaaS-vs-Spatial gap stays inside
the run-to-run variance band.

**Finding 2: The coal-belt advantage does *not* reproduce on real
ENTSO-E 2020 data.** In the synthetic experiment of §7.3, GreenFaaS
beat Spatial by +3.5pp in the coal-belt topology (DE/GB/PL) by
exploiting intra-region temporal shifts. On real ENTSO-E 2020 traces
with the calibrated PL profile, this advantage disappears: Spatial
edges GreenFaaS by 1.3pp instead.

The reason is empirically clear. The synthetic carbon model in §7.3
used a region-amplitude of $\sim$50% (peak-to-trough), whereas real
ENTSO-E 2020 diurnal swings for DE and GB are closer to $\sim$30%
peak-to-trough (real DE range 170--380 g; real GB range 107--336 g),
and our calibrated PL has only $\sim$15% (coal base-load runs flat).
With smaller swings, the §4.3.9 idle-energy condition rules out most
temporal deferral as net-positive for carbon, and GreenFaaS's region
gate falls back to behaviour close to Spatial.

This is a useful empirical correction: the "GreenFaaS wins in
coal-belt" finding was partly driven by the synthetic-carbon
amplitude. The honest statement is that **GreenFaaS *matches*
Spatial across all topologies on real ENTSO-E 2020 data, including
coal-belt, and the difference is within run-to-run variance.**
GreenFaaS's distinct value over Spatial therefore rests on
robustness rather than dominance in any single regime.

**Finding 3: The do-no-harm property reproduces cleanly on real
data.** In both single-region scenarios on real DE and real CAISO
data, GreenFaaS matches FIFO byte-for-byte: 39.77 g and 50.17 g
respectively, identical to the FIFO baselines. GreenFaaS-v1 (the
ablation without the §4.3.9 idle-energy correction) loses 38--40\% to
FIFO in the same scenarios --- empirical confirmation that the
idle-energy correction is what produces do-no-harm, and that the
property holds equally well under real carbon-intensity dynamics as
under synthetic ones. Wait-Awhile loses 163--211\% to FIFO on real
data; the catastrophic batch-scheduler failure mode also reproduces
cleanly.

**Summary.** The real-carbon experiments validate (i) the headline
reduction in the 75--82\% range, (ii) the Wait-Awhile failure mode,
and (iii) the do-no-harm property. They temper the §7.3 claim that
GreenFaaS *outperforms* Spatial in coal-belt topologies: on real
ENTSO-E 2020 data, GreenFaaS *matches* Spatial across every
topology, with the advantage emerging only on synthetic data with
larger intra-region diurnal swings. The corrected positioning ---
GreenFaaS is the topology-robust scheduler that matches or
near-matches Spatial when Spatial works, and harmlessly falls back
to FIFO when Spatial does not --- is arguably a more honest claim
about a deployment-ready scheduler than ``always dominates.''
