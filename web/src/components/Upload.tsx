import { useEffect, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  LinearProgress,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import UploadFileRoundedIcon from "@mui/icons-material/UploadFileRounded";
import LinkRoundedIcon from "@mui/icons-material/LinkRounded";
import { uploadFile, createYoutubeJob, pollJob, listJobs, formatDuration } from "../api";
import type { Job } from "../api";
import { EDGE, MARK } from "../theme";

interface Props {
  onReady: (job: Job) => void;
  onOpenJob: (jobId: string) => void;
}

type Source = "file" | "youtube";

const STATUS_LABEL: Record<string, string> = {
  queued: "En cola",
  downloading: "Descargando",
  processing: "Procesando",
  done: "Listo",
  failed: "Falló",
};

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
    <Container maxWidth="lg" sx={{ py: { xs: 4, md: 6 } }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="overline" sx={{ display: "block" }}>
          Nueva producción
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          Procesar una grabación
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "62ch" }}>
          Sube un archivo o pega una URL de YouTube. Edgetape escanea, detecta los pasajes más
          fuertes y deja los clips listos para revisar.
        </Typography>
      </Box>

      <Box>
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
              border: `2px dashed ${dragging ? EDGE : "divider"}`,
              background: dragging ? "rgba(30,58,138,0.06)" : "background.paper",
              borderRadius: 2,
              p: { xs: 4, md: 7 },
              textAlign: "center",
              cursor: "pointer",
              transition: "border-color .2s ease, background .2s ease",
              "&:hover": { borderColor: EDGE },
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
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontFamily: "'Fragment Mono', monospace", mt: 0.5, display: "block" }}
                >
                  {job.progress}%
                </Typography>
              </Box>
            )}
          </Box>
        ) : (
          <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 640 }}>
            <Typography variant="overline" color="text.secondary" sx={{ display: "block" }}>
              Enlace
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
              <Button
                variant="contained"
                type="submit"
                disabled={busy || !url.trim()}
                sx={{ minWidth: 180 }}
              >
                {busy ? statusLabel : "Procesar video"}
              </Button>
            </Stack>
            {showProgress && (
              <Box sx={{ mt: 3 }}>
                <LinearProgress variant="determinate" value={job.progress} sx={{ height: 6 }} />
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontFamily: "'Fragment Mono', monospace", mt: 0.5, display: "block" }}
                >
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
      </Box>

      <Box sx={{ mt: 6 }}>
        <Stack direction="row" spacing={2} sx={{ alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", mb: 2 }}>
          <Box>
            <Typography variant="overline" sx={{ display: "block" }}>
              Tu material
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Retoma un video ya procesado para revisar sus clips y publicaciones.
            </Typography>
          </Box>
        </Stack>

        {recent.length === 0 ? (
          <Box
            sx={{
              p: 5,
              textAlign: "center",
              border: "1px dashed",
              borderColor: "divider",
              borderRadius: 2,
              bgcolor: "background.paper",
            }}
          >
            <Typography variant="body2" color="text.secondary">
              Todavía no procesaste ninguna grabación. Cuando lo hagas, aparecerá aquí.
            </Typography>
          </Box>
        ) : (
          <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflow: "hidden", bgcolor: "background.paper" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Video</TableCell>
                  <TableCell>Fuente</TableCell>
                  <TableCell align="right">Clips</TableCell>
                  <TableCell align="right">Duración</TableCell>
                  <TableCell>Fecha</TableCell>
                  <TableCell align="right">Estado</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {recent.slice(0, 10).map((j) => {
                  const ready = j.status === "done";
                  return (
                    <TableRow
                      key={j.id}
                      hover
                      onClick={() => ready && onOpenJob(j.id)}
                      sx={{ cursor: ready ? "pointer" : "default" }}
                    >
                      <TableCell sx={{ fontWeight: 600 }}>{j.filename}</TableCell>
                      <TableCell>{j.source === "youtube" ? "YouTube" : "archivo"}</TableCell>
                      <TableCell align="right" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                        {j.clip_count}
                      </TableCell>
                      <TableCell align="right" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                        {j.duration ? formatDuration(j.duration) : "—"}
                      </TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>
                        {new Date(j.created_at).toLocaleDateString("es-AR", {
                          day: "2-digit",
                          month: "short",
                          year: "numeric",
                        })}
                        {" · "}
                        {new Date(j.created_at).toLocaleTimeString("es-AR", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </TableCell>
                      <TableCell align="right">
                        <Chip
                          size="small"
                          label={STATUS_LABEL[j.status] ?? j.status}
                          variant={ready ? "filled" : "outlined"}
                          sx={{
                            bgcolor: ready ? MARK : "transparent",
                            color: ready ? "#14161A" : undefined,
                            borderColor: ready ? MARK : undefined,
                          }}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Box>
        )}
      </Box>
    </Container>
  );
}
