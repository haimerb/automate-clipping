import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  SelectChangeEvent,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import MovieFilterRoundedIcon from "@mui/icons-material/MovieFilterRounded";
import CheckCircleRoundedIcon from "@mui/icons-material/CheckCircleRounded";
import ErrorRoundedIcon from "@mui/icons-material/ErrorRounded";
import {
  EDGE,
  EDGE_SOFT,
  INK,
  MARK,
  MARK_SOFT,
  MUTED,
  RAIL,
  SURFACE_2,
} from "../theme";
import {
  generateVideo,
  getAccounts,
  getClips,
  getJob,
  listJobs,
  publishClip,
  setClipPublish,
} from "../api";
import type { Job, LinkedAccount } from "../api";

interface GenerateProps {
  onJobReady: (job: Job) => void;
  onOpenJob: (jobId: string) => void;
}

type GenerateStatus = "idle" | "generating" | "processing" | "done" | "failed";

interface GenerateResult {
  jobId: string;
  status: GenerateStatus;
  error?: string;
}

const DURATION_OPTIONS = [
  { value: 15, label: "15 seg" },
  { value: 30, label: "30 seg" },
  { value: 60, label: "60 seg" },
];

const STYLE_OPTIONS = [
  { value: "professional", label: "Profesional" },
  { value: "casual", label: "Casual" },
  { value: "energetic", label: "Enérgico" },
  { value: "cinematic", label: "Cinematográfico" },
];

const PLATFORM_OPTIONS = [
  { value: "youtube_shorts", label: "YouTube Shorts" },
  { value: "tiktok", label: "TikTok" },
  { value: "facebook_reels", label: "Facebook Reels" },
  { value: "instagram_reels", label: "Instagram Reels" },
];

const VOICE_OPTIONS = [
  { value: "es_mx_female", label: "Español (Mujer)" },
  { value: "es_mx_male", label: "Español (Hombre)" },
  { value: "en_us_female", label: "English (Woman)" },
  { value: "en_us_male", label: "English (Man)" },
];

export default function Generate({ onJobReady, onOpenJob }: GenerateProps) {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(30);
  const [style, setStyle] = useState("professional");
  const [platform, setPlatform] = useState("youtube_shorts");
  const [voice, setVoice] = useState("es_mx_female");
  const [autoPublish, setAutoPublish] = useState(false);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");

  const [result, setResult] = useState<GenerateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);

  useEffect(() => {
    getAccounts().then(setAccounts).catch(() => {});
    listJobs().then((jobs) => setRecentJobs(jobs.slice(0, 5))).catch(() => {});
  }, []);

  const platformAccounts = accounts.filter((a) => {
    if (platform === "youtube_shorts") return a.platform === "youtube";
    if (platform === "tiktok") return a.platform === "tiktok";
    if (platform === "facebook_reels") return a.platform === "facebook";
    if (platform === "instagram_reels") return a.platform === "instagram";
    return false;
  });

  async function handleGenerate() {
    if (!prompt.trim()) return;
    setLoading(true);
    setResult({ jobId: "", status: "generating" });

    try {
      const data = await generateVideo({
        prompt: prompt.trim(),
        duration,
        style,
        platform,
        voice,
        auto_publish: autoPublish && selectedAccount ? true : false,
        account_id: selectedAccount || undefined,
      });

      setResult({ jobId: data.job_id, status: "processing" });

      pollJob(data.job_id);
    } catch (err: any) {
      setResult({ jobId: "", status: "failed", error: err.message });
      setLoading(false);
    }
  }

  async function pollJob(jobId: string) {
    const poll = async () => {
      try {
        const job = await getJob(jobId);
        if (job.status === "done") {
          setResult({ jobId, status: "done" });
          setLoading(false);
          const clips = await getClips(jobId);
          if (clips.length > 0) {
            for (const clip of clips) {
              if (!clip.publish) {
                await setClipPublish(jobId, clip.id, true);
              }
              if (autoPublish && selectedAccount) {
                const acct = accounts.find((a) => a.id === selectedAccount);
                if (acct) {
                  const plat = platform === "youtube_shorts" ? "youtube_shorts" : platform;
                  await publishClip(jobId, clip.id, plat, acct.name).catch(() => {});
                }
              }
            }
          }
          onJobReady(job);
          return;
        }
        if (job.status === "failed") {
          setResult({ jobId, status: "failed", error: job.error || "Error desconocido" });
          setLoading(false);
          return;
        }
        setTimeout(poll, 1000);
      } catch {
        setTimeout(poll, 2000);
      }
    };
    poll();
  }

  return (
    <Box sx={{ maxWidth: 960, mx: "auto", px: { xs: 2, md: 3 }, py: 4 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="overline" sx={{ display: "block", mb: 0.5 }}>
          Generador de video
        </Typography>
        <Typography variant="h4" sx={{ mb: 1 }}>
          Crea videos con IA
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 600 }}>
          Describe el video que quieres crear, ajusta las opciones y deja que la IA haga el trabajo.
          Los videos generados se pueden publicar automáticamente en tus plataformas.
        </Typography>
      </Box>

      <Stack spacing={3}>
        <Paper
          sx={{
            p: 3,
            border: `1px solid ${RAIL}`,
            borderRadius: 2,
          }}
        >
          <Typography variant="h6" sx={{ mb: 2, display: "flex", alignItems: "center", gap: 1 }}>
            <AutoAwesomeRoundedIcon sx={{ color: MARK, fontSize: "1.2rem" }} />
            Prompt
          </Typography>
          <TextField
            multiline
            rows={4}
            fullWidth
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe el video que quieres crear...&#10;&#10;Ejemplo: Un video profesional mostrando los 5 mejores consejos de productividad para emprendedores, con transiciones suaves y música de fondo inspiradora."
            sx={{
              mb: 2,
              "& .MuiOutlinedInput-root": {
                fontFamily: "'Hanken Grotesk', sans-serif",
                fontSize: "0.9rem",
                lineHeight: 1.6,
              },
            }}
          />
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
            <Chip
              size="small"
              label={`${prompt.split(/\s+/).filter(Boolean).length} palabras`}
              sx={{
                fontFamily: "'Fragment Mono', monospace",
                fontSize: "0.6rem",
                backgroundColor: EDGE_SOFT,
                color: MUTED,
              }}
            />
            <Chip
              size="small"
              label={`${duration} seg`}
              sx={{
                fontFamily: "'Fragment Mono', monospace",
                fontSize: "0.6rem",
                backgroundColor: MARK_SOFT,
                color: INK,
              }}
            />
            <Chip
              size="small"
              label={STYLE_OPTIONS.find((s) => s.value === style)?.label}
              sx={{
                fontFamily: "'Fragment Mono', monospace",
                fontSize: "0.6rem",
                backgroundColor: EDGE_SOFT,
                color: MUTED,
              }}
            />
          </Stack>
        </Paper>

        <Paper
          sx={{
            p: 3,
            border: `1px solid ${RAIL}`,
            borderRadius: 2,
          }}
        >
          <Typography variant="h6" sx={{ mb: 2 }}>
            Opciones
          </Typography>
          <Stack spacing={3}>
            <Box>
              <Typography variant="body2" sx={{ mb: 1, fontWeight: 600, color: "text.secondary" }}>
                Duración
              </Typography>
              <Stack direction="row" spacing={1}>
                {DURATION_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    variant={duration === opt.value ? "contained" : "outlined"}
                    size="small"
                    onClick={() => setDuration(opt.value)}
                    sx={{
                      minWidth: 80,
                      fontFamily: "'Fragment Mono', monospace",
                      fontSize: "0.65rem",
                    }}
                  >
                    {opt.label}
                  </Button>
                ))}
              </Stack>
            </Box>

            <Box>
              <Typography variant="body2" sx={{ mb: 1, fontWeight: 600, color: "text.secondary" }}>
                Estilo
              </Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
                {STYLE_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    variant={style === opt.value ? "contained" : "outlined"}
                    size="small"
                    onClick={() => setStyle(opt.value)}
                    sx={{
                      fontFamily: "'Fragment Mono', monospace",
                      fontSize: "0.65rem",
                    }}
                  >
                    {opt.label}
                  </Button>
                ))}
              </Stack>
            </Box>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel>Plataforma</InputLabel>
                <Select
                  value={platform}
                  label="Plataforma"
                  onChange={(e: SelectChangeEvent) => setPlatform(e.target.value)}
                >
                  {PLATFORM_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel>Voz</InputLabel>
                <Select
                  value={voice}
                  label="Voz"
                  onChange={(e: SelectChangeEvent) => setVoice(e.target.value)}
                >
                  {VOICE_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
          </Stack>
        </Paper>

        <Paper
          sx={{
            p: 3,
            border: `1px solid ${RAIL}`,
            borderRadius: 2,
          }}
        >
          <Typography variant="h6" sx={{ mb: 2 }}>
            Publicación automática
          </Typography>
          <Stack spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={autoPublish}
                  onChange={(e) => setAutoPublish(e.target.checked)}
                  size="small"
                />
              }
              label={
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  Publicar automáticamente al generar
                </Typography>
              }
            />
            {autoPublish && (
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: "center" }}>
                <FormControl size="small" sx={{ minWidth: 200 }}>
                  <InputLabel>Cuenta vinculada</InputLabel>
                  <Select
                    value={selectedAccount}
                    label="Cuenta vinculada"
                    onChange={(e: SelectChangeEvent) => setSelectedAccount(e.target.value)}
                  >
                    <MenuItem value="">
                      <em>Seleccionar cuenta</em>
                    </MenuItem>
                    {platformAccounts.map((acct) => (
                      <MenuItem key={acct.id} value={acct.id}>
                        {acct.name} ({acct.handle})
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                {platformAccounts.length === 0 && (
                  <Alert severity="info" sx={{ flex: 1 }}>
                    No hay cuentas vinculadas para esta plataforma.{" "}
                    <Typography
                      component="span"
                      sx={{
                        color: EDGE,
                        cursor: "pointer",
                        fontWeight: 600,
                        "&:hover": { textDecoration: "underline" },
                      }}
                      onClick={() => window.dispatchEvent(new CustomEvent("edgetape:navigate", { detail: "accounts" }))}
                    >
                      Vincular cuenta
                    </Typography>
                  </Alert>
                )}
              </Stack>
            )}
          </Stack>
        </Paper>

        {result && result.status === "failed" && (
          <Alert
            severity="error"
            icon={<ErrorRoundedIcon />}
            sx={{ borderRadius: 2 }}
          >
            {result.error || "Error al generar el video. Intenta de nuevo."}
          </Alert>
        )}

        {result && result.status === "done" && (
          <Alert
            severity="success"
            icon={<CheckCircleRoundedIcon />}
            sx={{ borderRadius: 2 }}
          >
            Video generado exitosamente. Redirigiendo al carrete...
          </Alert>
        )}

        <Button
          variant="contained"
          size="large"
          fullWidth
          onClick={handleGenerate}
          disabled={loading || !prompt.trim()}
          startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeRoundedIcon />}
          sx={{
            py: 1.5,
            fontSize: "0.85rem",
            fontFamily: "'Fragment Mono', monospace",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          {loading ? "Generando..." : "Generar video"}
        </Button>

        {recentJobs.length > 0 && (
          <Paper
            sx={{
              p: 3,
              border: `1px solid ${RAIL}`,
              borderRadius: 2,
            }}
          >
            <Typography variant="h6" sx={{ mb: 2 }}>
              Generaciones recientes
            </Typography>
            <Stack spacing={1}>
              {recentJobs.map((j) => (
                <Box
                  key={j.id}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 2,
                    p: 1.5,
                    borderRadius: 1.5,
                    border: `1px solid ${RAIL}`,
                    cursor: j.status === "done" ? "pointer" : "default",
                    "&:hover": j.status === "done" ? { backgroundColor: EDGE_SOFT } : {},
                    transition: "background-color 0.15s ease",
                  }}
                  onClick={() => j.status === "done" && onOpenJob(j.id)}
                >
                  <MovieFilterRoundedIcon sx={{ color: MUTED, fontSize: "1.2rem" }} />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 600,
                        fontSize: "0.82rem",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {j.filename}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{
                        fontFamily: "'Fragment Mono', monospace",
                        fontSize: "0.58rem",
                      }}
                    >
                      {new Date(j.created_at).toLocaleDateString("es-MX", {
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </Typography>
                  </Box>
                  <Chip
                    size="small"
                    label={j.status === "done" ? "Listo" : j.status === "processing" ? "Procesando..." : j.status}
                    sx={{
                      fontFamily: "'Fragment Mono', monospace",
                      fontSize: "0.58rem",
                      backgroundColor: j.status === "done" ? "rgba(30,122,70,.08)" : j.status === "processing" ? MARK_SOFT : SURFACE_2,
                      color: j.status === "done" ? "#1E7A46" : j.status === "processing" ? INK : MUTED,
                    }}
                  />
                </Box>
              ))}
            </Stack>
          </Paper>
        )}
      </Stack>
    </Box>
  );
}
