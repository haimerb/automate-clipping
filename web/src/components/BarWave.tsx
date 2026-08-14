import { useEffect, useRef, useState } from "react";

interface Props {
  seed: string;
  active?: boolean;
}

function hash(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return h;
}

export default function BarWave({ seed, active }: Props) {
  const [bars, setBars] = useState<number[]>([]);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const width = ref.current?.clientWidth ?? 320;
    const count = Math.max(24, Math.floor(width / 8));
    const rngState = hash(seed);
    const next: number[] = [];
    for (let i = 0; i < count; i++) {
      const v = Math.abs(Math.sin(i * 0.9 + rngState) * Math.cos(i * 0.13 + (rngState % 7) + 1));
      const peak = Math.abs(Math.sin(i * 0.31 + rngState * 0.5));
      next.push(Math.max(0.12, Math.min(1, v * 0.7 + peak * 0.6)));
    }
    setBars(next);
  }, [seed]);

  return (
    <span ref={ref} className={`wave${active ? " wave--active" : ""}`} aria-hidden="true">
      {bars.map((h, i) => (
        <i key={i} style={{ height: `${Math.round(h * 100)}%` }} />
      ))}
    </span>
  );
}
