#!/bin/bash
# Run the full GreenFaaS evaluation pipeline on whatever data is available.
#
# Honours GREENFAAS_CARBON_DIR if set; otherwise uses real_data/carbon.
# If a real Azure trace is present in real_data/azure_2021/, runs the
# real-workload experiments; otherwise uses the synthetic-but-schema-
# faithful workload.
#
# Usage:
#   ./run-all.sh                                          # use defaults
#   GREENFAAS_CARBON_DIR=real_data/carbon_em ./run-all.sh # use real EM data
#
set -e
cd "$(dirname "$0")"

CARBON_DIR="${GREENFAAS_CARBON_DIR:-real_data/carbon}"
echo "================================================================"
echo "GreenFaaS full evaluation pipeline"
echo "================================================================"
echo "Carbon data:   $CARBON_DIR"

# Check carbon data exists.
if [ ! -d "$CARBON_DIR" ]; then
  echo "ERROR: Carbon directory $CARBON_DIR does not exist."
  echo "  Either keep the default real_data/carbon, or fetch real"
  echo "  ElectricityMaps data:"
  echo "    export ELECTRICITYMAPS_API_KEY=<your-key>"
  echo "    python scripts/fetch_electricitymaps.py \\"
  echo "      --zones DE FR GB US-CAL-CISO PL \\"
  echo "      --start 2024-01-01 --end 2024-01-15 \\"
  echo "      --out-dir $CARBON_DIR --rename"
  exit 1
fi
ls "$CARBON_DIR"

# Check Azure trace presence.
AZURE_2021=""
for cand in \
  real_data/azure_2021/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  real_data/azure_2021/AzureFunctionsInvocationTrace2021.csv ; do
  if [ -f "$cand" ]; then AZURE_2021="$cand"; break; fi
done
if [ -n "$AZURE_2021" ]; then
  echo "Azure 2021 trace: $AZURE_2021 (will be used)"
else
  echo "Azure 2021 trace: not found (will use schema-faithful synthetic workload)"
fi
echo

export GREENFAAS_CARBON_DIR="$CARBON_DIR"

echo "[1/13] Verifying analytical lemma..."
python scripts/verify_tradeoff.py | tail -1

echo
echo "[2/13] Headline experiment (synthetic 5-region)..."
python scripts/run_experiment.py

echo
echo "[3/13] Real-carbon headline (§7.2.1)..."
python scripts/run_real_carbon.py

echo
echo "[4/13] Real-carbon topology sweep (§7.3.1)..."
python scripts/run_real_topology.py

echo
echo "[5/13] Fair-Wait-Awhile parameterization (§7.2.2)..."
python scripts/run_fair_waitawhile.py

echo
echo "[6/13] Lechowicz baseline (§7.2.3)..."
python scripts/run_lechowicz.py

echo
echo "[7/13] Fine-grained do-no-harm (§7.4.1)..."
python scripts/run_fine_donoharm.py

echo
echo "[8/13] Multi-seed variance (5 seeds, all setups)..."
python scripts/run_multi_seed.py

echo
echo "[9/13] Multi-baseline comparison, canonical workload (incl. GreenCourier)..."
python scripts/run_multibaseline.py

echo
echo "[10/13] Multi-baseline comparison, long-deadline stress workload..."
python scripts/run_multibaseline.py --catalog long-deadline

echo
echo "[11/13] Interactive routing at equal guards..."
python scripts/run_interactive_guard.py

echo
echo "[12/13] Runtime crossover..."
python scripts/run_runtime_crossover.py

echo
echo "[13/13] Idle-power and keep-alive sensitivity..."
python scripts/run_idle_sensitivity.py

if [ -n "$AZURE_2021" ]; then
  echo
  echo "[bonus] Real Azure workload run..."
  python scripts/run_real_traces.py \
    --azure-2021-csv "$AZURE_2021" \
    --carbon-dir "$CARBON_DIR" \
    --max-rows 5000000
fi

echo
echo "================================================================"
echo "All experiments done. Results in results/*.csv."
echo "Regenerate figures and rebuild PDFs:"
echo "  python scripts/sensitivity_sweep.py"
echo "  python scripts/motivation_figure.py"
echo "  python scripts/tradeoff_figure.py"
echo "  cp figures/*.png latex/figures/"
echo "  cd latex && ./build.sh all"
echo "================================================================"
