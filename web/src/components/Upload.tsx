import { Fragment, useEffect, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  LinearProgress,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import UploadFileRoundedIcon from "@mui/icons-material/UploadFileRounded";
import LinkRoundedIcon from "@mui/icons-material/LinkRounded";
import { uploadFile, createYoutubeJob, pollJob, listJobs, formatDuration } from "../api";
import type { Job } from "../api";
import { MARK } from "../theme";

interface Props {
  onReady: (job: Job) => void;
  onOpenJob: (jobId: string) => void;
}

type Source = "file" | "youtube";

export default function Upload({ onReady, onOpenJob }: Props) {
  const [source, setSource] = useState<Source>("file");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [label, setLabel] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [recent, setRecent] = useState<Job[]>([]);

  useEffect(() => {
    listJobs()
      .then(setRecent)
      .catch(() => setRecent([]));
  }, []);

  async function process(promise: Promise<Job>, doneLabel: string) {
    setError(null);
    setBusy(true);
    setLabel(doneLabel);
    try {
      const created = await promise;
      setJob(created);
      const finished = await pollJob(created.id, setJob);
      onReady(finished);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Algo salió mal");
      setBusy(false);
    }
  }

  function startFile(file: File) {
    void process(uploadFile(file), file.name);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) startFile(file);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    void process(createYoutubeJob(trimmed), trimmed);
  }

  const showProgress = busy && job && job.status !== "done";
  const statusLabel = label
    ? job?.status === "downloading"
      ? "Descargando el video…"
      : job?.status === "processing"
        ? "Buscando los momentos fuertes…"
        : "Subiendo archivo…"
    : "Procesando…";

  return (
    <Container maxWidth="lg" sx={{ py: { xs: 5, md: 9 } }}>
      <Typography variant="overline" sx={{ display: "block" }}>
        edgetape — clipping automático
      </Typography>
      <Typography variant="h3" sx={{ mt: 1, maxWidth: "20ch" }}>
        Una grabación. Un carrete con los <em>momentos</em> que importan.
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mt: 1.5, maxWidth: "62ch" }}>
        Edgetape escanea tu audio o video, <b>detecta los pasajes más fuertes</b> y los deja
        listos en un carrete de repaso — cada uno para cortar y exportar como clip para Shorts,
        TikTok y Reels.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ mt: 3, alignItems: "center", flexWrap: "wrap" }}>
        {["INGEST", "DETECT", "CUT", "POST"].map((stage, i) => (
          <Fragment key={stage}>
            {i > 0 && <Box aria-hidden sx={{ width: 22, height: 1, bgcolor: "divider" }} />}
            <Typography
              sx={{
                fontFamily: "'Fragment Mono', monospace",
                fontSize: "0.6rem",
                letterSpacing: "0.18em",
                color: i === 0 ? MARK : "text.secondary",
                textTransform: "uppercase",
              }}
            >
              {stage}
            </Typography>
          </Fragment>
        ))}
      </Stack>

      <Box sx={{ mt: 5 }}>
        <Tabs
          value={source}
          onChange={(_, v) => setSource(v as Source)}
          sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}
        >
          <Tab
            value="file"
            label="Archivo"
            icon={<UploadFileRoundedIcon fontSize="small" />}
            iconPosition="start"
            disabled={busy}
          />
          <Tab
            value="youtube"
            label="YouTube"
            icon={<LinkRoundedIcon fontSize="small" />}
            iconPosition="start"
            disabled={busy}
          />
        </Tabs>

        {source === "file" ? (
          <Box
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => document.getElementById("file-input")?.click()}
            sx={{
              border: `2px dashed ${dragging ? "#1E3A8A" : "divider"}`,
              borderColor: dragging ? "#1E3A8A" : "divider",
              background: dragging ? "rgba(30,58,138,0.06)" : "background.paper",
              borderRadius: 1,
              p: { xs: 4, md: 7 },
              textAlign: "center",
              cursor: "pointer",
              transition: "border-color .2s ease, background .2s ease",
              "&:hover": { borderColor: "#1E3A8A" },
            }}
          >
            <input
              id="file-input"
              type="file"
              accept="video/*,audio/*,.mp3,.wav,.mp4,.mov,.m4a,.ogg"
              disabled={busy}
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) startFile(file);
              }}
            />
            <Typography variant="overline" color="text.secondary" sx={{ display: "block" }}>
              INGEST
            </Typography>
            <Typography variant="h6" sx={{ mt: 1.5 }}>
              {busy && label ? label : "Suelta una grabación para empezar"}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              MP4 · MOV · WAV · MP3 — cualquier cosa que hayas grabado
            </Typography>
            <Button variant="contained" sx={{ mt: 2.5 }} disabled={busy}>
              {busy && label ? statusLabel : "Elegir un archivo"}
            </Button>
            {showProgress && (
              <Box sx={{ mt: 3 }}>
                <LinearProgress variant="determinate" value={job.progress} sx={{ height: 6 }} />
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "'Fragment Mono', monospace", mt: 0.5, display: "block" }}>
                  {job.progress}%
                </Typography>
              </Box>
            )}
          </Box>
        ) : (
          <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 640 }}>
            <Typography variant="overline" color="text.secondary" sx={{ display: "block" }}>
              ENLACE
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
              Pega una URL de YouTube y edgetape descarga el video automáticamente.
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              <TextField
                fullWidth
                placeholder="https://www.youtube.com/watch?v=…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={busy}
              />
              <Button variant="contained" type="submit" disabled={busy || !url.trim()} sx={{ minWidth: 180 }}>
                {busy ? statusLabel : "Procesar video"}
              </Button>
            </Stack>
            {showProgress && (
              <Box sx={{ mt: 3 }}>
                <LinearProgress variant="determinate" value={job.progress} sx={{ height: 6 }} />
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "'Fragment Mono', monospace", mt: 0.5, display: "block" }}>
                  {job.progress}%
                </Typography>
              </Box>
            )}
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        <Box
          aria-hidden
          sx={{
            mt: 6,
            height: 44,
            borderRadius: 1,
            border: "1px solid",
            borderColor: "divider",
            background: `repeating-linear-gradient(90deg, transparent 0 40px, ${MARK} 40px 44px, transparent 44px 48px)`,
            opacity: 0.35,
          }}
        />

        {recent.length > 0 && (
          <Box sx={{ mt: 5 }}>
            <Typography variant="overline" sx={{ display: "block" }}>
              TUS GRABACIONES
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
              Retoma un video ya procesado para revisar sus clips y publicaciones.
            </Typography>
            <List disablePadding sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
              {recent.slice(0, 8).map((j) => {
                const ready = j.status === "done";
                const statusLabel: Record<string, string> = {
                  queued: "En cola",
                  downloading: "Descargando",
                  processing: "Procesando",
                  done: "Listo",
                  failed: "Falló",
                };
                return (
                  <ListItemButton
                    key={j.id}
                    disabled={!ready}
                    onClick={() => onOpenJob(j.id)}
                    sx={{
                      borderBottom: "1px dashed",
                      borderColor: "divider",
                      "&:last-of-type": { borderBottom: "none" },
                      "&:hover": { background: "rgba(30,58,138,0.05)" },
                    }}
                  >
                    <ListItemText
                      primary={j.filename}
                      secondary={
                        <>
                          {new Date(j.created_at).toLocaleDateString("es-AR", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })}{" "}
                          · {new Date(j.created_at).toLocaleTimeString("es-AR", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}{" "}
                          · {j.clip_count} clips
                          {j.duration ? ` · ${formatDuration(j.duration)}` : ""}
                          {j.source === "youtube" ? " · YouTube" : " · archivo"}
                        </>
                      }
                      slotProps={{
                        primary: { sx: { fontWeight: 600, fontSize: "0.9rem" } },
                        secondary: { variant: "body2" },
                      }}
                    />
                    <Chip
                      size="small"
                      label={statusLabel[j.status] ?? j.status}
                      variant={ready ? "filled" : "outlined"}
                      sx={{
                        ml: 2,
                        bgcolor: ready ? MARK : "transparent",
                        color: ready ? "#14161A" : undefined,
                        borderColor: ready ? MARK : undefined,
                        flexShrink: 0,
                      }}
                    />
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
        )}
      </Box>
    </Container>
  );
}
