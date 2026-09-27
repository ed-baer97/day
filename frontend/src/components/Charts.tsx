export type ChartSeries = { name: string; color: string; values: number[]; dashed?: boolean };

const W = 640;
const PAD = { l: 52, r: 12, t: 14, b: 26 };

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * p;
}

export function fmtShort(v: number) {
  const a = Math.abs(v);
  if (a >= 10_000) return `${Math.round(v / 1000)}k`;
  if (a >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return `${Math.round(v)}`;
}

function Legend({ series }: { series: ChartSeries[] }) {
  if (series.length < 2) return null;
  return (
    <div className="chart-legend">
      {series.map((s) => (
        <span key={s.name}>
          <i style={{ background: s.color }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

function Grid({ max, h }: { max: number; h: number }) {
  const rows = 4;
  return (
    <g className="chart-grid">
      {Array.from({ length: rows + 1 }, (_, i) => {
        const v = (max * i) / rows;
        const y = PAD.t + (h - PAD.t - PAD.b) * (1 - i / rows);
        return (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} />
            <text x={PAD.l - 8} y={y + 4} textAnchor="end">
              {fmtShort(v)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function XLabels({ labels, x, h }: { labels: string[]; x: (i: number) => number; h: number }) {
  const every = Math.max(1, Math.ceil(labels.length / 10));
  return (
    <g className="chart-x">
      {labels.map((l, i) =>
        i % every === 0 ? (
          <text key={i} x={x(i)} y={h - 8} textAnchor="middle">
            {l}
          </text>
        ) : null
      )}
    </g>
  );
}

export function LineChart({
  labels,
  series,
  height = 200,
}: {
  labels: string[];
  series: ChartSeries[];
  height?: number;
}) {
  const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
  const n = labels.length;
  const x = (i: number) => PAD.l + (n <= 1 ? 0 : (i * (W - PAD.l - PAD.r)) / (n - 1));
  const y = (v: number) => PAD.t + (height - PAD.t - PAD.b) * (1 - v / max);

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img">
        <Grid max={max} h={height} />
        {series.map((s) => (
          <polyline
            key={s.name}
            fill="none"
            style={{ stroke: s.color }}
            strokeWidth={2.5}
            strokeDasharray={s.dashed ? "6 5" : undefined}
            strokeLinejoin="round"
            points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
        ))}
        <XLabels labels={labels} x={x} h={height} />
      </svg>
      <Legend series={series} />
    </div>
  );
}

export function BarChart({
  labels,
  series,
  height = 200,
}: {
  labels: string[];
  series: ChartSeries[];
  height?: number;
}) {
  const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
  const n = Math.max(1, labels.length);
  const slot = (W - PAD.l - PAD.r) / n;
  const barW = Math.min(28, (slot * 0.7) / series.length);
  const groupW = barW * series.length;
  const x = (i: number) => PAD.l + slot * i + slot / 2;
  const plotH = height - PAD.t - PAD.b;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img">
        <Grid max={max} h={height} />
        {labels.map((_, i) =>
          series.map((s, j) => {
            const v = s.values[i] ?? 0;
            const bh = (plotH * v) / max;
            return (
              <rect
                key={`${i}-${s.name}`}
                x={x(i) - groupW / 2 + j * barW}
                y={PAD.t + plotH - bh}
                width={Math.max(1, barW - 2)}
                height={bh}
                rx={3}
                style={{ fill: s.color }}
              >
                <title>
                  {labels[i]} · {s.name}: {Math.round(v).toLocaleString("ru-RU")} л
                </title>
              </rect>
            );
          })
        )}
        <XLabels labels={labels} x={x} h={height} />
      </svg>
      <Legend series={series} />
    </div>
  );
}
