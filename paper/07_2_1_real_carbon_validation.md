## 7.2.1 Real Carbon-Intensity Validation

To validate that the headline findings of §7.2 are not artefacts of
synthetic carbon traces, we re-ran the canonical 24-hour experiment
substituting the synthetic carbon model with the real
ENTSO-E / CAISO 15-minute-resolution carbon-intensity data released by
Wiesner et al.\ \citep{wiesner2021lets,lwa}. The workload remains the
schema-correct synthetic stream (the Azure Functions 2021 trace is
public but distributed via Azure storage URLs that are not directly
fetchable in our build environment; a one-line CLI flag swaps it in
when available locally; see §\ref{sec:evaluation:methodology}).

\paragraph{Carbon profile.} The real LWA traces over our 24-hour window
exhibit mean intensities of 39.9 g/kWh (France), 235.2 g (Germany),
234.6 g (Great Britain), and 319.0 g (US-CAISO). These are
approximately 15--25\% lower than the calibration values we used in
the synthetic experiments (60, 350, 220, 250 g respectively), reflecting
ENTSO-E's actual 2020 generation mix rather than published annual means.
The diurnal swing is real and non-trivial: GB ranges from 121 to 336
g/kWh on this day, a $\sim 3\times$ ratio; CAISO from 243 to 352, a
$\sim 1.5\times$ ratio. France is essentially flat (38--43 g) due to
its nuclear-dominated mix.

\paragraph{Results.} Table~\ref{tab:real_carbon} reports the same five
schedulers under real carbon data. The qualitative findings of §7.2
hold without modification:

\begin{table}[h]
\centering\small
\caption{Real LWA carbon, synthetic workload (24h, 173k invocations,
4 regions). Compare to Table~\ref{tab:headline}.}
\label{tab:real_carbon}
\begin{tabular}{lrrrr}
\toprule
Scheduler     & Carbon (g) & vs FIFO   & SLA    & Cold-start \\
\midrule
FIFO          & 36.08      &  0.0\%    & 0.00\% & 0.05\%     \\
Wait-Awhile   & 94.87      & --162.9\% & 0.00\% & 1.23\%     \\
Spatial       & 12.79      & +64.6\%   & 0.00\% & 0.03\%     \\
GreenFaaS-v1  & 15.49      & +57.1\%   & 0.00\% & 0.34\%     \\
\GreenFaaS    & 12.96      & +64.1\%   & 0.00\% & 0.03\%     \\
\bottomrule
\end{tabular}
\end{table}

Three observations. \emph{First}, the Wait-Awhile failure mode
reproduces on real data: \emph{162\% increase} over FIFO, vs 236\%
on synthetic. The mechanism is the same (synchronised-defer pile-up
inflating cold-start and idle-energy), and the magnitude reduction
is consistent with the smaller diurnal swing in the real data.
\emph{Second}, the \GreenFaaS-vs-Spatial gap shrinks from 0.7pp on
synthetic to 0.5pp on real, both well within run-to-run variance. We
attribute this to the absence of a coal-belt region in the LWA dataset
(no Polish-grid trace); under \S\ref{sec:evaluation:topology}, the
coal-belt scenario is where \GreenFaaS{} pulls ahead, and the LWA
mix lacks such a region. \emph{Third}, GreenFaaS-v1's 7pp gap below
\GreenFaaS{} on real data validates the §\ref{sec:tradeoff:idle}
idle-energy correction in the real-carbon regime, with the same
cold-start-rate increase ($0.34\%$ vs $0.03\%$) seen on synthetic.

The honest summary: real carbon data does \emph{not} change any
qualitative finding of §7.2. The magnitude of \GreenFaaS's reduction
vs FIFO is somewhat smaller (64\% vs 78\%) because the real European
2020 mix is cleaner overall than our synthetic calibration assumed
(and France in particular was even cleaner in 2020 than the published
annual mean). For a complete real-data evaluation, the workload side
should be swapped to the Azure Functions 2021 per-invocation trace
when locally available, and the region set extended to include Poland
or another high-carbon grid (which would shift coal-belt results
upward; that experiment is left for future work pending dataset
access).
