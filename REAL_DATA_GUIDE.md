# Running GreenFaaS with Real Data

This guide walks through downloading the public Azure Functions traces
and real-time carbon-intensity data from ElectricityMaps, then running
the full GreenFaaS evaluation pipeline on this real data.

**You must do these steps on a machine with general internet access.**
The build environment used to produce this repository has restricted
network egress and cannot reach `*.blob.core.windows.net` or
`api.electricitymap.org`; the data must be fetched locally.

---

## Quick reference: what data we need

| Source            | Dataset                                  | Size    | Format     | Used for |
| ----------------- | ---------------------------------------- | ------- | ---------- | -------- |
| Azure (Microsoft) | Azure Functions Invocation Trace 2021   | ~150 MB | `.rar`     | §7.2 headline (real workload) |
| Azure (Microsoft) | Azure Functions Dataset 2019            | ~3 GB   | `.tar.xz`  | §7.2 alt (aggregated workload) |
| ElectricityMaps   | Historical carbon intensity, 5+ zones    | ~10 MB  | JSON → CSV | §7.2.1, §7.3.1 (real carbon)  |

You don't need both Azure datasets. The 2021 trace is per-invocation
(more useful and smaller), and is the primary target. The 2019 trace is
aggregated (per-minute counts + duration percentiles); use it if you
specifically want the year of Shahrad et al.

---

## Step 1: Clone or unpack this repository

```bash
unzip greenfaas.zip
cd greenfaas
# Verify the lemma still runs locally:
python scripts/verify_tradeoff.py
# Should print: "All trade-off lemma checks passed."
```

---

## Step 2: Download the Azure Functions Invocation Trace 2021

```bash
cd /path/to/greenfaas
mkdir -p real_data/azure_2021
cd real_data/azure_2021

# Primary download. Microsoft uses Azure-managed blob storage; the URL is
# documented in the dataset README at
#   github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsInvocationTrace2021.md
# If the URL has changed, check that README for the current link.

curl -L -o AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar \
  "https://azurecloudpublicdataset2.blob.core.windows.net/azurepublicdatasetv2/azurefunctions_dataset2021/AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar"

# Extract. The .rar is a RAR archive; you'll need `unrar` (apt install unrar)
# or 7-Zip on Windows.
unrar x AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar

# After extraction you should have:
#   AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt
# This is the per-invocation trace with columns:
#   app, func, end_timestamp, duration
# (See our greenfaas/traces/azure_2021.py loader; the schema is the
# published one.)

# Sanity check:
head -3 AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt
wc -l AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt
# Expect: tens of millions of invocations over the two-week window.

cd ../..
```

If the curl URL returns 404, check the AzureFunctionsInvocationTrace2021.md
README on GitHub for the current download link — Microsoft occasionally
re-shards their public datasets and rotates URLs.

---

## Step 3: (Optional) Download the Azure Functions Dataset 2019

Only do this if you specifically want the aggregated 2019 trace.

```bash
cd /path/to/greenfaas
mkdir -p real_data/azure_2019
cd real_data/azure_2019

curl -L -o azurefunctions-dataset2019.tar.xz \
  "https://azurepublicdatasettraces.blob.core.windows.net/azurepublicdatasetv2/azurefunctions_dataset2019/azurefunctions-dataset2019.tar.xz"

tar -xJf azurefunctions-dataset2019.tar.xz

# You should now see files like:
#   invocations_per_function_md.anon.d01.csv  (and d02 through d14)
#   function_durations_percentiles.anon.d01.csv
#   app_memory_percentiles.anon.d01.csv

cd ../..
```

---

## Step 4: Fetch real carbon-intensity data from ElectricityMaps

Set your API key as an environment variable. **Never commit the key to
source control.**

```bash
export ELECTRICITYMAPS_API_KEY="<your-key-here>"
```

Then fetch carbon data for the five regions we use (DE, FR, GB, CAISO, PL)
for a recent two-week window (matching the Azure trace duration):

```bash
cd /path/to/greenfaas

# Replace the start/end dates with whatever your subscription tier permits.
# ElectricityMaps free tier covers ~1 month of recent history; commercial
# tier covers multi-year history. The Azure trace is from January 2021,
# so the "matched" experiment uses 2021-01-12 to 2021-01-26; you'll need
# at least a commercial subscription to reach those dates.

python scripts/fetch_electricitymaps.py \
  --zones DE FR GB US-CAL-CISO PL \
  --start 2024-01-01 \
  --end 2024-01-15 \
  --out-dir real_data/carbon_em \
  --rename
```

The `--rename` flag maps `US-CAL-CISO` (ElectricityMaps' zone code) to
`US-CAISO.csv` (the filename our existing `load_carbon_model_from_dir`
loader expects). With that flag set you'll get:

```
real_data/carbon_em/
  DE.csv
  FR.csv
  GB.csv
  PL.csv             <- real, no longer the calibrated synthetic
  US-CAISO.csv       <- renamed from US-CAL-CISO
```

Each file is in LWA schema (`Time,Carbon Intensity`) and loads through
the same loader as the existing `real_data/carbon/` files.

If your subscription cannot reach the Azure-trace 2021 dates, just use
recent dates and report it as "real carbon data from a recent window";
the qualitative findings (carbon-aware FaaS scheduling matters) do not
depend on date alignment.

---

## Step 5: Run the full evaluation pipeline on real data

The trace loaders accept the published Azure schemas without
modification. Two options:

### Option A: Real workload + real carbon (the full real-data run)

```bash
cd /path/to/greenfaas

# Headline §7.2 with REAL workload and REAL carbon:
python scripts/run_real_traces.py \
  --azure-2021-csv real_data/azure_2021/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  --carbon-dir real_data/carbon_em \
  --duration-h 24 \
  --output-csv results/real_headline.csv

# Topology sweep on real carbon, real workload:
python scripts/run_real_topology.py \
  --azure-2021-csv real_data/azure_2021/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  --carbon-dir real_data/carbon_em \
  --output-csv results/real_topology.csv

# 5-seed variance test on real workload:
python scripts/run_multi_seed.py \
  --azure-2021-csv real_data/azure_2021/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  --carbon-dir real_data/carbon_em
```

If a script doesn't expose all of these flags yet, check its `main()`;
the loader functions all do, and adding a `--azure-2021-csv` flag to
any runner is a 3-line change.

### Option B: Synthetic workload + real ElectricityMaps carbon

This is what the current paper reports as "real-LWA-carbon
validation"; running it with ElectricityMaps data (and real PL, no longer
calibrated) tightens the §7.3.1 results:

```bash
python scripts/run_real_carbon.py --carbon-dir real_data/carbon_em
python scripts/run_real_topology.py --carbon-dir real_data/carbon_em
python scripts/run_lechowicz.py  # Lechowicz baseline on real carbon
```

---

## Step 6: Regenerate paper tables and figures

Once the results CSVs are produced, regenerate figures:

```bash
# Sensitivity sweep figures (regenerates *.png with new data):
python scripts/sensitivity_sweep.py

# Motivation figure (only depends on carbon trace + workload generation):
python scripts/motivation_figure.py

# Copy updated figures into the LaTeX build directory:
cp figures/*.png latex/figures/

# Rebuild the paper:
cd latex
./build.sh all
```

The headline tables in `latex/sections/07_evaluation.tex`,
`07_2_1_real_carbon.tex`, and `07_3_1_real_topology.tex` use hand-typed
numerical values; update them to match your new CSV outputs by editing
the LaTeX directly.

---

## Sanity checks

After all the above:

1. **Lemma still verifies**:
   ```bash
   python scripts/verify_tradeoff.py
   # Should print "All trade-off lemma checks passed."
   ```

2. **Both PDFs build cleanly**:
   ```bash
   cd latex && ./build.sh all
   # Should produce paper.pdf, paper_elsevier.pdf, paper_elsevier_final.pdf.
   ```

3. **Real-carbon numbers are in plausible range**:
   - FR mean: 30-80 g (nuclear-dominated)
   - DE mean: 200-400 g (mixed)
   - GB mean: 150-300 g (cleaning gas)
   - PL mean: 600-900 g (coal-dominated)
   - US-CAISO mean: 200-350 g (renewable + gas)

   If your fetched numbers are outside these ranges, you may have
   selected an atypical date window (e.g., winter cold snap in PL).

---

## Troubleshooting

**`curl: (22) The requested URL returned error: 404`**
Microsoft re-sharded the dataset. Check the dataset README at
`github.com/Azure/AzurePublicDataset` for the current URL.

**`unrar: command not found`**
Install RAR support: `apt install unrar` (Ubuntu/Debian) or
`brew install unrar` (macOS) or use 7-Zip on Windows.

**`HTTP 401` from ElectricityMaps**
Either the API key is wrong, expired, or you're calling a zone your
subscription tier doesn't cover. Verify at
https://api.electricitymap.org/v3/zones (with auth-token header)
which zones are accessible to you.

**`HTTP 429` from ElectricityMaps**
Rate-limited. The `fetch_electricitymaps.py` script sleeps 1s between
requests; increase if you're still hitting limits.

**Out-of-memory loading the 2021 trace**
The full 2021 trace is large (~150 MB compressed, multi-GB uncompressed).
Use the loader's `--duration-h` or `--n-invocations` flags to subset.

---

## What to do once real data is loaded

Compare the new real-data results against the synthetic-data baseline.
The qualitative findings expected to hold:
- Wait-Awhile catastrophically inflates carbon (>2× FIFO).
- Lechowicz performs worst of all baselines.
- GreenFaaS and Spatial both capture most available savings (60-80% vs FIFO).
- GreenFaaS = FIFO byte-for-byte in single-region scenarios (do-no-harm).
- GreenFaaS--Spatial gap within 1-2 percentage points.

The quantitative magnitudes will shift with the actual workload pattern;
report the new numbers honestly. If the qualitative ordering changes
(e.g., Lechowicz suddenly beats GreenFaaS on some setup), that is a
finding worth investigating, not a bug.
