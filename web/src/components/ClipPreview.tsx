import { useRef, useState } from "react";
import { Box } from "@mui/material";
import { formatDuration, formatTimecode, previewUrl, thumbUrl } from "../api";
import type { Clip } from "../api";
import { MARK } from "../theme";

interface Props {
  jobId: string;
  clip: Clip;
  variant?: "thumb" | "player";
  hoverPlay?: boolean;
  showTimecode?: boolean;
  showExport?: boolean;
}

export default function ClipPreview({
  jobId,
  clip,
  variant = "thumb",
  hoverPlay = false,
  showTimecode = false,
  showExport = false,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [hovering, setHovering] = useState(false);
  const exported = clip.exported && Boolean(clip.export_name);
  const vertical = exported && variant === "player";

  function onEnter() {
    if (!hoverPlay || !exported || !videoRef.current) return;
    setHovering(true);
    void videoRef.current.play().catch(() => {});
  }

  function onLeave() {
    if (!videoRef.current) return;
    setHovering(false);
    videoRef.current.pause();
    videoRef.current.currentTime = 0;
  }

  return (
    <Box
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      sx={{
        position: "relative",
        borderRadius: 1,
        overflow: "hidden",
        border: "1px solid",
        borderColor: "divider",
        background: "#000",
        aspectRatio: vertical ? "9/16" : "16/9",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: hoverPlay && exported ? "pointer" : "default",
      }}
    >
      <img
        src={thumbUrl(jobId, clip.id)}
        alt={clip.title}
        loading="lazy"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
      />
      {exported && (
        <video
          ref={videoRef}
          src={previewUrl(jobId, clip.id)}
          controls={variant === "player"}
          muted
          autoPlay={variant === "player"}
          playsInline
          preload={variant === "player" ? "auto" : "metadata"}
          loop={hovering}
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            objectFit: "contain",
            display: "block",
            background: "rgba(0,0,0,0.35)",
          }}
        />
      )}

      {showTimecode && (
        <Box
          sx={{
            position: "absolute",
            bottom: 8,
            left: 8,
            fontFamily: "'Fragment Mono', monospace",
            fontSize: "0.62rem",
            background: "rgba(20,22,26,0.78)",
            color: "#fff",
            px: 0.75,
            py: 0.25,
            borderRadius: 0.5,
            letterSpacing: "0.04em",
          }}
        >
          {formatTimecode(clip.start)} → {formatTimecode(clip.end)}
        </Box>
      )}
      {showExport && exported && (
        <Box
          sx={{
            position: "absolute",
            top: 6,
            right: 6,
            background: "rgba(20,22,26,0.78)",
            color: MARK,
            fontFamily: "'Fragment Mono', monospace",
            fontSize: "0.56rem",
            px: 0.5,
            py: 0.15,
            borderRadius: 0.5,
            letterSpacing: "0.06em",
          }}
        >
          ▶ exportado
        </Box>
      )}
      {!exported && variant === "thumb" && (
        <Box
          sx={{
            position: "absolute",
            bottom: 8,
            right: 8,
            background: "rgba(20,22,26,0.78)",
            color: "#fff",
            fontFamily: "'Fragment Mono', monospace",
            fontSize: "0.58rem",
            px: 0.6,
            py: 0.2,
            borderRadius: 0.5,
          }}
        >
          {formatDuration(clip.duration)}
        </Box>
      )}
      <Box aria-hidden sx={{ position: "absolute", inset: 0, pointerEvents: "none", boxShadow: `inset 0 0 0 1px rgba(20,22,26,0.12)`, borderRadius: 1 }} />
    </Box>
  );
}
