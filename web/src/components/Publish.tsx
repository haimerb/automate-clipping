import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  FormControlLabel,
  IconButton,
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
  accountsForPlatform,
  formatDuration,
  getAccounts,
  getPosts,
  patchJobSettings,
  publishClip,
  setClipPublish,
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

interface Destination {
  platform: string;
  account: string;
}

const DEFAULT_PLATFORM = "youtube_shorts";

export default function Publish({ job, clips, onUpdateClip, onBack, onJobChange }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [publishingAll, setPublishingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [dests, setDests] = useState<Record<string, Destination[]>>({});
  const [draftPlatform, setDraftPlatform] = useState<Record<string, string>>({});
  const [draftAccount, setDraftAccount] = useState<Record<string, string>>({});
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
        for (const clip of selected) {
          const platform = draftPlatform[clip.id] ?? DEFAULT_PLATFORM;
          const available = accountsForPlatform(list, platform);
          if (!draftAccount[clip.id] && available[0]) {
            setDraftAccount((prev) => ({ ...prev, [clip.id]: available[0].name }));
          }
        }
      })
      .catch(() => setAccounts([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  useEffect(() => setAutoPublish(job.auto_publish), [job.auto_publish]);

  const postByDest = useMemo(() => {
    const map: Record<string, PlatformPost> = {};
    for (const p of posts) {
      const key = `${p.clip_id}|${p.platform}`;
      if (key in map) continue;
      map[key] = p;
    }
    return map;
  }, [posts]);

  const destCount = useMemo(
    () => selected.reduce((acc, clip) => acc + (dests[clip.id] ?? []).length, 0),
    [selected, dests],
  );

  function defaultDraft(clipId: string): { platform: string; account: string } {
    const platform = draftPlatform[clipId] ?? DEFAULT_PLATFORM;
    const available = accountsForPlatform(accounts, platform);
    const account = available.some((a) => a.name === draftAccount[clipId])
      ? draftAccount[clipId]
      : available[0]?.name ?? "";
    return { platform, account };
  }

  function changeDraftPlatform(clipId: string, platform: string) {
    setDraftPlatform((prev) => ({ ...prev, [clipId]: platform }));
    const available = accountsForPlatform(accounts, platform);
    setDraftAccount((prev) => ({ ...prev, [clipId]: available[0]?.name ?? "" }));
  }

  function addDestination(clip: Clip) {
    const draft = defaultDraft(clip.id);
    if (!draft.platform) return;
    setDests((prev) => ({
      ...prev,
      [clip.id]: [...(prev[clip.id] ?? []), { ...draft }],
    }));
  }

  function removeDestination(clipId: string, index: number) {
    setDests((prev) => ({
      ...prev,
      [clipId]: (prev[clipId] ?? []).filter((_, i) => i !== index),
    }));
  }

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

  async function publishOneDestination(clip: Clip, dest: Destination, index: number) {
    const key = `${clip.id}|${index}`;
    setBusy(key);
    setError(null);
    try {
      await publishClip(job.id, clip.id, dest.platform, dest.account || null);
      setDoneCount((c) => c + 1);
      await refreshPosts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo publicar el clip");
    } finally {
      setBusy(null);
    }
  }

  async function publishAllDestinations() {
    const targets = selected.flatMap((clip) =>
      (dests[clip.id] ?? []).map((dest) => ({ clip, dest })),
    );
    if (targets.length === 0) return;
    setPublishingAll(true);
    setError(null);
    setDoneCount(0);
    for (const { clip, dest } of targets) {
      try {
        await publishClip(job.id, clip.id, dest.platform, dest.account || null);
        setDoneCount((c) => c + 1);
      } catch (err) {
        if (!error) {
          setError(err instanceof Error ? err.message : "No se pudo publicar todo");
        }
      }
    }
    await refreshPosts();
    setPublishingAll(false);
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
            {doneCount} {doneCount === 1 ? "publicación creada" : "publicaciones creadas"} — revisa
            cada destino para ver el estado y el enlace.
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
                  <Typography variant="body2" color="text.secondary" sx={{ maxWidth: "58ch" }}>
                    Configura en cada tarjeta a qué plataforma y canal publicar cada clip. Un clip
                    puede ir a varios destinos. Aquí puedes lanzar todos los destinos de una vez.
                  </Typography>
                </Box>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: "center" }}>
                  <Typography
                    variant="body2"
                    sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.72rem" }}
                  >
                    {destCount} {destCount === 1 ? "destino" : "destinos"}
                  </Typography>
                  <Button
                    variant="contained"
                    onClick={() => void publishAllDestinations()}
                    disabled={publishingAll || destCount === 0}
                    startIcon={
                      publishingAll ? <CircularProgress size={16} color="inherit" /> : undefined
                    }
                  >
                    {publishingAll
                      ? "Publicando…"
                      : `Publicar ${destCount} ${destCount === 1 ? "destino" : "destinos"}`}
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
                    Al activarla, cada clip que marques en el carrete se exporta y publica solo a
                    YouTube, sin pasar por esta pantalla.
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
                const clipDests = dests[clip.id] ?? [];
                const draft = defaultDraft(clip.id);
                const draftAvailable = accountsForPlatform(accounts, draft.platform);
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

                      <Box
                        sx={{
                          mt: 2,
                          borderTop: "1px dashed",
                          borderColor: "divider",
                          pt: 2,
                        }}
                      >
                        <Typography variant="overline" sx={{ display: "block" }}>
                          Destinos
                        </Typography>
                        <Stack spacing={1} sx={{ mt: 1 }}>
                          {clipDests.length === 0 && (
                            <Typography variant="body2" color="text.secondary">
                              Añade un destino (plataforma y canal) para este clip.
                            </Typography>
                          )}
                          {clipDests.map((dest, index) => {
                            const post = postByDest[`${clip.id}|${dest.platform}`];
                            const key = `${clip.id}|${index}`;
                            const busyHere = busy === key;
                            return (
                              <Paper
                                key={key}
                                variant="outlined"
                                sx={{ p: 1.25, bgcolor: "background.paper" }}
                              >
                                <Stack
                                  direction={{ xs: "column", sm: "row" }}
                                  spacing={1.5}
                                  sx={{
                                    justifyContent: "space-between",
                                    alignItems: { xs: "stretch", sm: "center" },
                                  }}
                                >
                                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                                    <Chip
                                      size="small"
                                      label={PLATFORM_LABELS[dest.platform] ?? dest.platform}
                                      variant="outlined"
                                    />
                                    <Typography
                                      variant="body2"
                                      color="text.secondary"
                                      sx={{ fontSize: "0.78rem" }}
                                    >
                                      {dest.account
                                        ? `→ ${dest.account}`
                                        : "→ sin cuenta vinculada"}
                                    </Typography>
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
                                  </Stack>
                                  <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                                    {post?.url && (
                                      <Button
                                        size="small"
                                        href={post.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        sx={{ fontSize: "0.7rem" }}
                                      >
                                        {post.status === "publicado" ? "Ver" : "Subirlo"} ↗
                                      </Button>
                                    )}
                                    <Button
                                      size="small"
                                      variant="contained"
                                      disabled={busyHere || publishingAll}
                                      onClick={() => void publishOneDestination(clip, dest, index)}
                                      startIcon={
                                        busyHere ? (
                                          <CircularProgress size={14} color="inherit" />
                                        ) : undefined
                                      }
                                    >
                                      {busyHere ? "Publicando…" : "Publicar"}
                                    </Button>
                                    <IconButton
                                      size="small"
                                      aria-label="quitar destino"
                                      onClick={() => removeDestination(clip.id, index)}
                                      disabled={publishingAll}
                                    >
                                      ✕
                                    </IconButton>
                                  </Stack>
                                </Stack>
                              </Paper>
                            );
                          })}
                        </Stack>

                        <Stack
                          direction={{ xs: "column", sm: "row" }}
                          spacing={1.5}
                          sx={{ mt: 1.5, alignItems: { xs: "stretch", sm: "center" } }}
                        >
                          <Select
                            size="small"
                            value={draft.platform}
                            onChange={(e) => changeDraftPlatform(clip.id, e.target.value)}
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
                            value={draft.account}
                            onChange={(e) =>
                              setDraftAccount((prev) => ({ ...prev, [clip.id]: e.target.value }))
                            }
                            sx={{ minWidth: 190 }}
                          >
                            <MenuItem value="">— sin cuenta —</MenuItem>
                            {draftAvailable.map((a) => (
                              <MenuItem key={a.id} value={a.name}>
                                {a.name}
                                {a.handle ? ` (${a.handle})` : ""}
                              </MenuItem>
                            ))}
                          </Select>
                          <Button
                            variant="outlined"
                            onClick={() => addDestination(clip)}
                            disabled={publishingAll}
                          >
                            Añadir destino
                          </Button>
                        </Stack>
                      </Box>

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
