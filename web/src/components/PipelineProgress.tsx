import { Box, LinearProgress, Typography } from "@mui/material";
import CheckRoundedIcon from "@mui/icons-material/CheckRounded";
import type { Job } from "../api";
import { EDGE, EDGE_SOFT, INK, MARK, MONO, RAIL, SUCCESS } from "../theme";

interface Stage {
  key: string;
  label: string;
  caption: string;
}

const STAGES: Stage[] = [
  { key: "queued", label: "En cola", caption: "esperando turno" },
  { key: "downloading", label: "Descargando", caption: "obteniendo el video" },
  { key: "processing", label: "Procesando", caption: "transcripción y detección" },
  { key: "exporting", label: "Exportando", caption: "cortando clips" },
  { key: "done", label: "Listo", caption: "clips disponibles" },
];

function stageIndex(status: string): number {
  return STAGES.findIndex((s) => s.key === status);
}

interface Props {
  job: Job;
}

export default function PipelineProgress({ job }: Props) {
  const current = stageIndex(job.status);
  const progress = job.progress ?? 0;

  return (
    <Box component="section" aria-label="Progreso del procesamiento" sx={{ mt: 3 }}>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1,
          mb: 1,
        }}
      >
        <Typography sx={{ fontFamily: MONO, fontSize: "0.62rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "text.secondary" }}>
          Pipeline
        </Typography>
        <Typography sx={{ fontFamily: MONO, fontSize: "0.62rem", color: "text.secondary" }}>
          {progress}%
        </Typography>
      </Box>

      <Box
        role="list"
        aria-label="Etapas del pipeline"
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${STAGES.length}, 1fr)`,
          gap: 0.5,
          mb: 2,
        }}
      >
        {STAGES.map((stage, i) => {
          const isCurrent = stage.key === job.status;
          const isDone = current > i || job.status === "done";
          const activeColor = job.status === "done" ? "rgba(30,122,70,.12)" : EDGE_SOFT;
          return (
            <Box
              key={stage.key}
              role="listitem"
              aria-current={isCurrent ? "step" : undefined}
              sx={{
                textAlign: "center",
                px: 0.5,
                py: 1,
                borderRadius: 1,
                border: "1px solid",
                borderColor: isCurrent ? MARK : RAIL,
                background: isDone ? activeColor : "transparent",
                opacity: i > current && job.status !== "done" ? 0.45 : 1,
                transition: "all 0.25s ease",
              }}
            >
              <Box
                sx={{
                  width: 26,
                  height: 26,
                  mx: "auto",
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: isDone ? (job.status === "done" ? SUCCESS : EDGE) : "transparent",
                  border: isCurrent ? `2px solid ${MARK}` : isDone ? "none" : `1px solid ${RAIL}`,
                  color: isDone ? "#fff" : isCurrent ? MARK : "text.secondary",
                  fontSize: "0.78rem",
                  fontFamily: MONO,
                  fontWeight: 700,
                  transition: "all 0.25s ease",
                }}
              >
                {isDone ? <CheckRoundedIcon sx={{ fontSize: 14 }} /> : isCurrent ? "▸" : i + 1}
              </Box>
              <Typography
                sx={{
                  mt: 0.75,
                  fontFamily: MONO,
                  fontSize: "0.58rem",
                  fontWeight: isCurrent ? 700 : 500,
                  color: isCurrent ? INK : "text.secondary",
                  lineHeight: 1.2,
                }}
              >
                {stage.label}
              </Typography>
              <Typography
                sx={{
                  fontSize: "0.54rem",
                  color: "text.secondary",
                  lineHeight: 1.2,
                  mt: 0.25,
                }}
              >
                {stage.caption}
              </Typography>
            </Box>
          );
        })}
      </Box>

      <LinearProgress
        variant="determinate"
        value={job.status === "done" ? 100 : Math.min(99, progress)}
        sx={{ height: 6 }}
      />
    </Box>
  );
}