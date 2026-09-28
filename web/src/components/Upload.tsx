import { useEffect, useState } from "react";
import type { DragEvent, FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Checkbox,
  Container,
  FormControl,
  FormControlLabel,
  FormHelperText,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
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
import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import {
  uploadFileWithProgress,
  createUrlJob,
  pollJob,
  listJobs,
  formatDuration,
  getAccounts,
  generateVideo,
  getJob,
} from "../api";
import type { Job, LinkedAccount } from "../api";
import { EDGE, MARK, MONO, ON_ACCENT } from "../theme";
import PipelineProgress from "./PipelineProgress";

interface Props {
  onReady: (job: Job) => void;
  onOpenJob: (jobId: string) => void;
}

type Source = "file" | "url" | "ai";

const PLATFORM_MAX: Record<string, number> = {
  youtube_shorts: 60,
  tiktok: 60,
  facebook_reels: 90,
  instagram_reels: 90,
  youtube: 180,
  otros: 120,
};

const PLATFORM_LABEL: Record<string, string> = {
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  facebook_reels: "Facebook Reels",
  instagram_reels: "Instagram Reels",
  youtube: "YouTube (video)",
  otros: "Otro formato",
};

const GENERATE_DURATIONS = [15, 30, 60, 90, 120, 180];

const STYLES: Record<string, string> = {
  professional: "Profesional",
  casual: "Casual",
  dramatic: "Dramático",
  motivational: "Motivacional",
  educational: "Educativo",
};

const VOICES: Record<string, string> = {
  es_mx_female: "Mujer (es-MX)",
  es_mx_male: "Hombre (es-MX)",
  es_es_female: "Mujer (es-ES)",
  es_es_male: "Hombre (es-ES)",
};

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
  const [uploadPct, setUploadPct] = useState<number | null>(null);

  const [prompt, setPrompt] = useState("");
  const [genPlatform, setGenPlatform] = useState("youtube_shorts");
  const [genDuration, setGenDuration] = useState(30);
  const [style, setStyle] = useState("professional");
  const [voice, setVoice] = useState("es_mx_female");
  const [autoPublish, setAutoPublish] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);

  useEffect(() => {
    listJobs()
      .then(setRecent)
      .catch(() => setRecent([]));
    getAccounts()
      .then(setAccounts)
      .catch(() => setAccounts([]));
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
    setUploadPct(0);
    void process(
      uploadFileWithProgress(file, (uploaded, total) => {
        setUploadPct(total > 0 ? Math.round((uploaded / total) * 100) : 0);
      }),
      file.name,
    ).finally(() => setUploadPct(null));
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
    void process(createUrlJob(trimmed), trimmed);
  }

  function onGenPlatformChange(value: string) {
    setGenPlatform(value);
    const max = PLATFORM_MAX[value] ?? 120;
    if (genDuration > max) {
      const allowed = GENERATE_DURATIONS.filter((d) => d <= max);
      setGenDuration(allowed.length ? allowed[allowed.length - 1] : genDuration);
    }
  }

  async function onGenSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    setLabel("Video IA");
    try {
      const { job_id } = await generateVideo({
        prompt: trimmed,
        duration: genDuration,
        style,
        platform: genPlatform,
        voice,
        auto_publish: autoPublish,
        account_id: autoPublish && accountId ? accountId : undefined,
      });
      const created = await getJob(job_id);
      setJob(created);
      const finished = await pollJob(job_id, setJob);
      onReady(finished);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Algo salió mal");
      setBusy(false);
    }
  }

  const showProgress = busy && job && job.status !== "done";
  const statusLabel = label
    ? job?.status === "downloading"
      ? "Descargando el video…"
      : job?.status === "processing"
        ? label === "Video IA"
          ? "Generando el video con IA…"
          : "Buscando los momentos fuertes…"
        : label === "Video IA"
          ? "Generando el video con IA…"
          : "Subiendo archivo…"
    : "Procesando…";

  return (
    <Container component="section" maxWidth="lg" sx={{ py: { xs: 5, md: 7 } }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="overline" sx={{ display: "block" }}>
          Nueva producción
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          Procesar una grabación
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "62ch" }}>
          Sube un archivo, pega una URL (YouTube, Twitch, Zoom…) o genera un video directamente
          con IA. Edgetape escanea, detecta los pasajes más fuertes y deja los clips listos para revisar.
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
            value="url"
            label="Enlace"
            icon={<LinkRoundedIcon fontSize="small" />}
            iconPosition="start"
            disabled={busy}
          />
          <Tab
            value="ai"
            label="IA"
            icon={<AutoAwesomeRoundedIcon fontSize="small" />}
            iconPosition="start"
            disabled={busy}
          />
        </Tabs>

        {source === "ai" ? (
          <Box component="form" onSubmit={onGenSubmit} sx={{ maxWidth: 760 }}>
            <Typography variant="overline" color="text.secondary" sx={{ display: "block" }}>
              Genera con IA
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
              Edgetape escribe el guion, narra con voz sintética y monta el video para el formato
              que elijas. Todo por plataforma: vertical para Shorts/TikTok/Reels, horizontal para YouTube.
            </Typography>

            <TextField
              fullWidth
              multiline
              minRows={3}
              maxRows={5}
              label="¿Sobre qué quieres el video?"
              placeholder="El secreto para vender más es entender la emoción de tus clientes…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={busy}
              sx={{ mb: 2 }}
            />

            <Stack spacing={2} sx={{ mb: 2 }}>
              <FormControl size="small" fullWidth>
                <InputLabel>Plataforma</InputLabel>
                <Select
                  value={genPlatform}
                  label="Plataforma"
                  onChange={(e) => onGenPlatformChange(e.target.value)}
                  disabled={busy}
                >
                  {Object.entries(PLATFORM_LABEL).map(([key, label]) => (
                    <MenuItem key={key} value={key}>
                      {label} · máx {PLATFORM_MAX[key]}s
                    </MenuItem>
                  ))}
                </Select>
                <FormHelperText>
                  El formato de salida depende del destino: {PLATFORM_LABEL.youtube} sale horizontal,
                  el resto vertical.
                </FormHelperText>
              </FormControl>

              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <FormControl size="small" fullWidth>
                  <InputLabel>Duración</InputLabel>
                  <Select
                    value={genDuration}
                    label="Duración"
                    onChange={(e) => setGenDuration(Number(e.target.value))}
                    disabled={busy}
                  >
                    {GENERATE_DURATIONS.filter((d) => d <= (PLATFORM_MAX[genPlatform] ?? 120)).map(
                      (d) => (
                        <MenuItem key={d} value={d}>
                          {d} segundos
                        </MenuItem>
                      ),
                    )}
                  </Select>
                </FormControl>
                <FormControl size="small" fullWidth>
                  <InputLabel>Estilo</InputLabel>
                  <Select
                    value={style}
                    label="Estilo"
                    onChange={(e) => setStyle(e.target.value)}
                    disabled={busy}
                  >
                    {Object.entries(STYLES).map(([key, label]) => (
                      <MenuItem key={key} value={key}>
                        {label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" fullWidth>
                  <InputLabel>Voz</InputLabel>
                  <Select
                    value={voice}
                    label="Voz"
                    onChange={(e) => setVoice(e.target.value)}
                    disabled={busy}
                  >
                    {Object.entries(VOICES).map(([key, label]) => (
                      <MenuItem key={key} value={key}>
                        {label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Stack>

              <FormControlLabel
                control={
                  <Checkbox
                    checked={autoPublish}
                    onChange={(e) => setAutoPublish(e.target.checked)}
                    disabled={busy}
                  />
                }
                label="Publicarlo automáticamente al terminar"
              />
              {autoPublish && (
                <FormControl size="small" fullWidth>
                  <InputLabel>Cuenta destino</InputLabel>
                  <Select
                    value={accountId}
                    label="Cuenta destino"
                    onChange={(e) => setAccountId(e.target.value)}
                    disabled={busy}
                  >
                    {accounts.map((a) => (
                      <MenuItem key={a.id} value={a.id}>
                        {a.name} ({a.platform})
                      </MenuItem>
                    ))}
                  </Select>
                  {accounts.length === 0 && (
                    <FormHelperText>
                      No tenés cuentas vinculadas. Publicá desde el panel CUENTAS.
                    </FormHelperText>
                  )}
                </FormControl>
              )}
            </Stack>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: "center" }}>
              <Button
                variant="contained"
                type="submit"
                disabled={busy || !prompt.trim() || (autoPublish && !accountId)}
                sx={{ minWidth: 180 }}
              >
                {busy ? (job && job.status !== "done" ? statusLabel : "Procesando…") : "Generar video"}
              </Button>
              <Typography variant="caption" color="text.secondary">
                Aparecerá en tu lista con un clip listo para revisar y publicar.
              </Typography>
            </Stack>

            {showProgress && job && (
              <Box sx={{ mt: 3 }}>
                <PipelineProgress job={job} />
              </Box>
            )}
          </Box>
        ) : source === "file" ? (
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
            {uploadPct !== null && (
              <Box sx={{ mt: 2.5, textAlign: "left" }} aria-live="polite">
                <LinearProgress
                  variant="determinate"
                  value={uploadPct}
                  sx={{ height: 6, borderRadius: 99 }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                  Subiendo… {uploadPct}%
                </Typography>
              </Box>
            )}
            {showProgress && job && (
              <Box sx={{ mt: 3, textAlign: "left" }}>
                <PipelineProgress job={job} />
              </Box>
            )}
          </Box>
        ) : (
          <Box component="form" onSubmit={onSubmit} sx={{ maxWidth: 640 }}>
            <Typography variant="overline" color="text.secondary" sx={{ display: "block" }}>
              Enlace
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
              Pega una URL de YouTube, Twitch, Zoom… y Edgetape descarga el video automáticamente.
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              <TextField
                fullWidth
                placeholder="https://www.youtube.com/watch?v=… o twitch.tv/…"
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
            {showProgress && job && (
              <Box sx={{ mt: 3 }}>
                <PipelineProgress job={job} />
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
          <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflowX: "auto", bgcolor: "background.paper" }}>
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
                      <TableCell>{j.source === "youtube" || j.source === "url" ? "Enlace" : j.source === "generate" ? "IA" : "archivo"}</TableCell>
                      <TableCell align="right" sx={{ fontFamily: MONO, fontSize: "0.78rem" }}>
                        {j.clip_count}
                      </TableCell>
                      <TableCell align="right" sx={{ fontFamily: MONO, fontSize: "0.78rem" }}>
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
                            color: ready ? ON_ACCENT : undefined,
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