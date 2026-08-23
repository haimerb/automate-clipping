import { Box, Button, Card, Typography } from "@mui/material";
import BarWave from "./BarWave";
import ClipPreview from "./ClipPreview";
import { formatDuration, formatTimecode } from "../api";
import type { Clip } from "../api";
import { EDGE, INK, MARK, MONO } from "../theme";

interface Props {
  jobId: string;
  clip: Clip;
  active: boolean;
  onSelect: (clip: Clip) => void;
  onTogglePublish: (clip: Clip, publish: boolean) => void;
}

export default function ClipCard({ jobId, clip, active, onSelect, onTogglePublish }: Props) {
  return (
    <Card
      onClick={() => onSelect(clip)}
      sx={{
        p: 2,
        display: "flex",
        flexDirection: "column",
        gap: 1.5,
        cursor: "pointer",
        border: active
          ? `2px solid ${EDGE}`
          : clip.publish
            ? `2px solid ${MARK}`
            : "1px solid",
        borderColor: clip.publish ? MARK : "divider",
        transition: "transform .22s ease, border-color .22s ease, box-shadow .22s ease",
        "&:hover": {
          transform: "translateY(-4px)",
          boxShadow: "0 18px 40px -24px rgba(20,22,26,.45)",
          borderColor: EDGE,
        },
      }}
    >
      <ClipPreview
        jobId={jobId}
        clip={clip}
        variant="thumb"
        hoverPlay
        showExport
      />

      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 1 }}>
        <Typography
          variant="overline"
          sx={{
            fontSize: "0.62rem",
            color: active ? INK : "text.primary",
            background: active ? MARK : "transparent",
            px: active ? 0.75 : 0,
            py: active ? 0.25 : 0,
            borderRadius: 0.5,
          }}
        >
          CLIP {String(clip.index).padStart(2, "0")}
        </Typography>
        <Typography sx={{ fontFamily: MONO, fontSize: "0.62rem", color: "text.secondary", whiteSpace: "nowrap" }}>
          {formatTimecode(clip.start)} → {formatTimecode(clip.end)}
        </Typography>
      </Box>

      <BarWave seed={`${clip.id}-${clip.index}`} active={active} />

      <Box sx={{ display: "flex", alignItems: "baseline", gap: 1 }}>
        <Typography sx={{ fontFamily: MONO, fontSize: "0.66rem", color: "primary.main", whiteSpace: "nowrap" }}>
          {formatDuration(clip.duration)}
        </Typography>
        <Typography sx={{ fontWeight: 600, fontSize: "0.98rem", lineHeight: 1.3 }}>
          {clip.title}
        </Typography>
      </Box>

      <Box sx={{ borderTop: "1px dashed", borderColor: "divider", pt: 1 }}>
        <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.82rem" }}>
          “{clip.line}”
        </Typography>
      </Box>

      <Button
        size="small"
        variant={clip.publish ? "contained" : "outlined"}
        color={clip.publish ? "secondary" : "primary"}
        onClick={(e) => {
          e.stopPropagation();
          onTogglePublish(clip, !clip.publish);
        }}
        sx={{ alignSelf: "flex-start", fontSize: "0.6rem", mt: 0.5 }}
      >
        {clip.publish ? "✔ Para publicar" : "Publicar"}
      </Button>
    </Card>
  );
}
