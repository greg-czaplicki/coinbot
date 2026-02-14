#!/usr/bin/env bash
set -euo pipefail

SAMPLES="${1:-20}"
OUT="${2:-docs/LATENCY_BASELINE.md}"

targets=(
  "https://clob.polymarket.com"
  "https://data-api.polymarket.com"
  "https://gamma-api.polymarket.com"
)

echo "# Latency Baseline" > "$OUT"
echo "" >> "$OUT"
echo "Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "$OUT"
echo "Samples per endpoint: $SAMPLES" >> "$OUT"
echo "" >> "$OUT"

for url in "${targets[@]}"; do
  echo "## $url" >> "$OUT"
  tmp="$(mktemp)"
  for _ in $(seq 1 "$SAMPLES"); do
    curl -s -o /dev/null -w "%{time_connect} %{time_starttransfer} %{time_total}\n" "$url" >> "$tmp"
    sleep 0.2
  done
  awk '
    {
      c[NR]=$1*1000;
      ttfb[NR]=$2*1000;
      total[NR]=$3*1000;
    }
    END {
      asort(c); asort(ttfb); asort(total);
      p50=int(NR*0.50); if (p50<1) p50=1;
      p95=int(NR*0.95); if (p95<1) p95=1;
      p99=int(NR*0.99); if (p99<1) p99=1;
      printf("|metric|p50_ms|p95_ms|p99_ms|\n");
      printf("|---|---:|---:|---:|\n");
      printf("|connect|%.1f|%.1f|%.1f|\n", c[p50], c[p95], c[p99]);
      printf("|ttfb|%.1f|%.1f|%.1f|\n", ttfb[p50], ttfb[p95], ttfb[p99]);
      printf("|total|%.1f|%.1f|%.1f|\n", total[p50], total[p95], total[p99]);
    }
  ' "$tmp" >> "$OUT"
  rm -f "$tmp"
  echo "" >> "$OUT"
done

echo "Wrote $OUT"
