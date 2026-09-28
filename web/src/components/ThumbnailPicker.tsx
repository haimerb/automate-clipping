import { useEffect, useState } from "react";
import { Box, Button, Paper, Skeleton, Typography } from "@mui/material";
import CheckRoundedIcon from "@mui/icons-material/CheckRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import { getClipThumbs, selectClipThumb, withToken } from "../api";
import type { Clip, Thumbnail } from "../api";
import { MONO, ON_ACCENT } from "../theme";

interface Props {
  jobId: string;
  clip: Clip;
  onUpdateClip: (clip: Clip) => void;
}

export default function ThumbnailPicker({ jobId, clip, onUpdateClip }: Props) {
  const [thumbs, setThumbs] = useState<Thumbnail[] | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(clip.thumbnail_index);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setThumbs(null);
    setError(null);
    getClipThumbs(jobId, clip.id)
      .then((res) => {
        if (!alive) return;
        setThumbs(res.thumbnails);
        setSelectedIndex(res.selected_index);
      })
      .catch(() => alive && setError("No se pudieron cargar las miniaturas"));
    return () => {
      alive = false;
    };
  }, [jobId, clip.id]);

  async function select(index: number) {
    if (busy !== null || index === selectedIndex) return;
    setBusy(index);
    setError(null);
    try {
      const updated = await selectClipThumb(jobId, clip.id, index);
      setSelectedIndex(index);
      onUpdateClip(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la miniatura");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, justifyContent: "space-between" }}>
        <Typography variant="overline" sx={{ display: "block" }}>
          Miniaturas
        </Typography>
        <Typography sx={{ fontFamily: MONO, fontSize: "0.6rem", color: "text.secondary" }}>
          {selectedIndex + 1} / {thumbs?.length ?? 5} seleccionada
        </Typography>
      </Box>

      {error && (
        <Typography variant="caption" color="error.main" sx={{ mt: 1, display: "block" }}>
          {error}
        </Typography>
      )}

      {!thumbs ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(84px, 1fr))",
            gap: 1.25,
            mt: 1.5,
          }}
        >
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" sx={{ aspectRatio: "9/16", borderRadius: 1 }} />
          ))}
          <Skeleton variant="rounded" sx={{ aspectRatio: "9/16", borderRadius: 1 }} />
        </Box>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(84px, 1fr))",
            gap: 1.25,
            mt: 1.5,
          }}
        >
          {thumbs.map((t, index) => {
            const isSelected = index === selectedIndex;
            const isBusy = busy === index;
            return (
              <Box key={t.url}>
                <Paper
                  component="button"
                  type="button"
                  aria-pressed={isSelected}
                  aria-label={`Seleccionar miniatura ${index + 1}`}
                  disabled={busy !== null}
                  onClick={() => void select(index)}
                  sx={{
                    width: "100%",
                    aspectRatio: "9/16",
                    p: 0,
                    overflow: "hidden",
                    position: "relative",
                    cursor: "pointer",
                    border: isSelected ? "3px solid var(--mui-palette-secondary-main)" : "1px solid",
                    borderColor: isSelected ? "var(--mui-palette-secondary-main)" : "divider",
                    borderRadius: 1.25,
                    backgroundColor: "transparent",
                    transition: "border-color .18s ease, transform .18s ease, box-shadow .18s ease",
                    "&:hover": {
                      transform: "translateY(-2px)",
                      boxShadow: "0 8px 20px -10px rgba(0,0,0,.5)",
                      borderColor: isSelected ? "var(--mui-palette-secondary-main)" : "var(--mui-palette-primary-main)",
                    },
                    "&:focus-visible": {
                      outline: "2px solid var(--mui-palette-primary-main)",
                      outlineOffset: 2,
                    },
                  }}
                >
                  <Box
                    component="img"
                    src={withToken(t.url)}
                    alt={`Opción ${index + 1}`}
                    loading="lazy"
                    sx={{
                      position: "absolute",
                      inset: 0,
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                      display: "block",
                    }}
                  />
                  {isSelected && (
                    <Box
                      aria-hidden
                      sx={{
                        position: "absolute",
                        inset: 0,
                        display: "flex",
                        alignItems: "flex-start",
                        justifyContent: "flex-end",
                        p: 0.5,
                        pointerEvents: "none",
                      }}
                    >
                      <Box
                        sx={{
                          width: 20,
                          height: 20,
                          borderRadius: "50%",
                          background: "var(--mui-palette-secondary-main)",
                          color: ON_ACCENT,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        <CheckRoundedIcon sx={{ fontSize: 14 }} />
                      </Box>
                    </Box>
                  )}
                  {isBusy && (
                    <Skeleton
                      variant="rectangular"
                      sx={{ position: "absolute", inset: 0, opacity: 0.55 }}
                    />
                  )}
                </Paper>
                <Typography
                  sx={{
                    mt: 0.5,
                    fontFamily: MONO,
                    fontSize: "0.56rem",
                    color: isSelected ? "var(--mui-palette-secondary-main)" : "text.secondary",
                    textAlign: "center",
                  }}
                >
                  {index + 1}
                </Typography>
              </Box>
            );
          })}
        </Box>
      )}

      <Button
        size="small"
        startIcon={<RefreshRoundedIcon />}
        onClick={() => {
          setThumbs(null);
          getClipThumbs(jobId, clip.id)
            .then((res) => {
              setThumbs(res.thumbnails);
              setSelectedIndex(res.selected_index);
            })
            .catch(() => setError("No se pudieron recargar las miniaturas"));
        }}
        disabled={busy !== null}
        sx={{ mt: 1.25, fontSize: "0.62rem" }}
      >
        Recargar miniaturas
      </Button>
    </Box>
  );
}