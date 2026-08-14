import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  FormControlLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import {
  PLATFORM_LABELS,
  POST_STATUS_LABELS,
  getAccounts,
  getPosts,
  patchJobSettings,
  publishAll,
  setClipPublish,
  formatDuration,
} from "../api";
import type { Clip, Job, LinkedAccount, PlatformPost } from "../api";
import ClipPreview from "./ClipPreview";
import MonetizationPanel from "./MonetizationPanel";
import { EDGE, MARK } from "../theme";

interface Props {
  job: Job;
  clips: Clip[];
  onUpdateClip: (clip: Clip) => void;
  onBack: () => void;
  onJobChange: (job: Job) => void;
}

export default function Publish({ job, clips, onUpdateClip, onBack, onJobChange }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [publishingAll, setPublishingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [account, setAccount] = useState<string>("");
  const [platform, setPlatform] = useState("youtube_shorts");
  const [autoPublish, setAutoPublish] = useState(job.auto_publish);
  const [posts, setPosts] = useState<PlatformPost[]>([]);
  const [doneCount, setDoneCount] = useState(0);

  const selected = clips.filter((c) => c.publish);

  async function refreshPosts() {
    try {
      setPosts(await getPosts(job.id));
    } catch {
      setPosts([]);
    }
  }

  useEffect(() => {
    void refreshPosts();
    getAccounts()
      .then((list) => {
        setAccounts(list);
        if (!list.some((a) => a.name === account)) {
          const first = list.find((a) => a.platform === "youtube") ?? list[0];
          if (first) setAccount(first.name);
        }
      })
      .catch(() => setAccounts([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  useEffect(() => setAutoPublish(job.auto_publish), [job.auto_publish]);

  const postByClip = useMemo(() => {
    const map: Record<string, PlatformPost> = {};
    for (const p of posts) {
      if (p.clip_id in map) continue;
      map[p.clip_id] = p;
    }
    return map;
  }, [posts]);

  async function togglePublish(clip: Clip, publish: boolean) {
    setBusy(clip.id);
    setError(null);
    try {
      const updated = await setClipPublish(job.id, clip.id, publish);
      onUpdateClip(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar");
    } finally {
      setBusy(null);
    }
  }

  async function toggleAutoPublish(next: boolean) {
    setAutoPublish(next);
    setError(null);
    try {
      const updated = await patchJobSettings(job.id, next);
      onJobChange(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la configuración");
      setAutoPublish(job.auto_publish);
    }
  }

  async function onPublishAll() {
    if (selected.length === 0) return;
    setPublishingAll(true);
    setError(null);
    setDoneCount(0);
    try {
      const created = await publishAll(job.id, platform, account || null);
      setDoneCount(created.length);
      await refreshPosts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo publicar todo");
    } finally {
      setPublishingAll(false);
    }
  }

  return (
    <Box component="section" sx={{ py: { xs: 5, md: 7 } }}>
      <Container maxWidth="lg">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" } }}
        >
          <Box>
            <Typography variant="overline">Sección 03 — lo que vas a publicar</Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              {selected.length} {selected.length === 1 ? "clip listo" : "clips listos"}
            </Typography>
          </Box>
          <Button variant="outlined" onClick={onBack} sx={{ alignSelf: { md: "flex-end" } }}>
            Volver al carrete
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        {doneCount > 0 && (
          <Alert severity="success" sx={{ mt: 3 }}>
            {doneCount} {doneCount === 1 ? "clip publicado" : "clips publicados"} — revisa cada
            tarjeta para ver el estado y el enlace.
          </Alert>
        )}

        {selected.length === 0 ? (
          <Paper sx={{ mt: 4, p: 5, textAlign: "center", borderStyle: "dashed" }}>
            <Typography variant="h6">Nada seleccionado para publicar todavía</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 2 }}>
              Regresa al carrete y marca los clips que vas a subir con el indicador{" "}
              <b>para publicar</b>.
            </Typography>
            <Button variant="contained" onClick={onBack}>
              Elegir clips
            </Button>
          </Paper>
        ) : (
          <>
            <Paper sx={{ mt: 4, p: 3, bgcolor: "#E9EEF9" }}>
              <Stack
                direction={{ xs: "column", md: "row" }}
                spacing={2}
                sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "center" } }}
              >
                <Box>
                  <Typography variant="overline" sx={{ display: "block" }}>
                    Publicación en bloque
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ maxWidth: "52ch" }}>
                    Exporta los {selected.length} clips y los publica en YouTube. Si tu cuenta está
                    conectada con las credenciales de la API, se suben solos; si no, quedan listos
                    con el enlace directo para subirlos.
                  </Typography>
                </Box>
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1.5}
                  sx={{ alignItems: { xs: "stretch", sm: "center" } }}
                >
                  <Select
                    size="small"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                    sx={{ minWidth: 170 }}
                  >
                    {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                      <MenuItem key={value} value={value}>
                        {label}
                      </MenuItem>
                    ))}
                  </Select>
                  <Select
                    size="small"
                    value={account}
                    onChange={(e) => setAccount(e.target.value)}
                    sx={{ minWidth: 170 }}
                  >
                    <MenuItem value="">— sin cuenta —</MenuItem>
                    {accounts.map((a) => (
                      <MenuItem key={a.id} value={a.name}>
                        {a.name}
                        {a.handle ? ` (${a.handle})` : ""}
                      </MenuItem>
                    ))}
                  </Select>
                  <Button
                    variant="contained"
                    onClick={() => void onPublishAll()}
                    disabled={publishingAll || selected.length === 0}
                    startIcon={
                      publishingAll ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : undefined
                    }
                  >
                    {publishingAll
                      ? "Publicando…"
                      : `Publicar ${selected.length} ${selected.length === 1 ? "clip" : "clips"}`}
                  </Button>
                </Stack>
              </Stack>
            </Paper>

            <Paper sx={{ mt: 2, p: 3 }}>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                spacing={1.5}
                sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", sm: "center" } }}
              >
                <Box>
                  <Typography variant="overline" sx={{ display: "block" }}>
                    Publicación automática
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ maxWidth: "56ch" }}>
                    Al activarla, cada clip que marques en el carrete se exporta y publica solo, sin
                    pasar por esta pantalla.
                  </Typography>
                </Box>
                <FormControlLabel
                  control={
                    <Switch
                      checked={autoPublish}
                      onChange={(e) => void toggleAutoPublish(e.target.checked)}
                      disabled={publishingAll}
                      sx={{
                        "& .MuiSwitch-switchBase.Mui-checked": { color: EDGE },
                        "& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track": {
                          backgroundColor: EDGE,
                        },
                      }}
                    />
                  }
                  label={autoPublish ? "Activada" : "Desactivada"}
                  sx={{ m: 0 }}
                />
              </Stack>
            </Paper>

            <Stack spacing={3} sx={{ mt: 3 }}>
              {selected.map((clip) => {
                const post = postByClip[clip.id];
                return (
                  <Paper
                    key={clip.id}
                    sx={{
                      p: 3,
                      display: "grid",
                      gridTemplateColumns: { xs: "1fr", md: "5fr 6fr" },
                      gap: 3,
                    }}
                  >
                    <Box>
                      <ClipPreview
                        jobId={job.id}
                        clip={clip}
                        variant="player"
                        showTimecode
                      />
                      <Typography
                        sx={{
                          mt: 1,
                          fontFamily: "'Fragment Mono', monospace",
                          fontSize: "0.66rem",
                          color: "text.secondary",
                        }}
                      >
                        {formatDuration(clip.duration)} · clip {String(clip.index).padStart(2, "0")}
                      </Typography>
                    </Box>

                    <Box>
                      <Stack
                        direction="row"
                        spacing={2}
                        sx={{ justifyContent: "space-between", alignItems: "flex-start" }}
                      >
                        <Box>
                          <Typography variant="h5">{clip.title}</Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            “{clip.line}”
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          {post && (
                            <Chip
                              size="small"
                              variant={post.status === "publicado" ? "filled" : "outlined"}
                              sx={{
                                bgcolor: post.status === "publicado" ? MARK : "transparent",
                                color: post.status === "publicado" ? "#14161A" : undefined,
                                borderColor: post.status === "publicado" ? MARK : undefined,
                              }}
                              label={POST_STATUS_LABELS[post.status] ?? post.status}
                            />
                          )}
                          <Button
                            size="small"
                            variant={clip.publish ? "contained" : "outlined"}
                            color={clip.publish ? "secondary" : "primary"}
                            onClick={() => void togglePublish(clip, !clip.publish)}
                            disabled={busy === clip.id || publishingAll}
                            sx={{ whiteSpace: "nowrap", color: clip.publish ? "#14161A" : undefined }}
                          >
                            {clip.publish ? "✔ Para publicar" : "Para publicar"}
                          </Button>
                        </Stack>
                      </Stack>

                      {post?.url && (
                        <Button
                          size="small"
                          href={post.url}
                          target="_blank"
                          rel="noreferrer"
                          startIcon={<span>↗</span>}
                          sx={{ mt: 0.5, fontSize: "0.7rem" }}
                        >
                          {post.status === "publicado"
                            ? "Ver en YouTube"
                            : "Subirlo ahora a YouTube Studio"}
                        </Button>
                      )}

                      <Box sx={{ mt: 2, borderTop: "1px dashed", borderColor: "divider", pt: 2 }}>
                        <MonetizationPanel jobId={job.id} clip={clip} refreshToken={posts.length} />
                      </Box>
                    </Box>
                  </Paper>
                );
              })}
            </Stack>
          </>
        )}
      </Container>
    </Box>
  );
}
