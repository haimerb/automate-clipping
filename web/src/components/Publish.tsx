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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import {
  HORIZONTAL_PLATFORMS,
  PLATFORM_LABELS,
  POST_STATUS_LABELS,
  accountsForPlatform,
  formatDuration,
  getAccounts,
  getPosts,
  maxSecondsFor,
  patchJobSettings,
  publishClip,
  request,
  setClipPublish,
  updateClip,
} from "../api";
import type { Clip, Destination, Job, LinkedAccount, PlatformPost } from "../api";
import ClipPreview from "./ClipPreview";
import MonetizationPanel from "./MonetizationPanel";
import { EDGE, MARK, MONO, ON_ACCENT } from "../theme";

interface QueueStatus {
  pending: number;
  tasks: Array<{ clip_id: string; platform: string; account: string; retries: number; status: string; next_retry: number | null }>;
  account_quotas: Record<string, { uploads_today: number; status: string; next_retry: number | null; quota_reset: number | null }>;
}

interface Props {
  job: Job;
  clips: Clip[];
  onUpdateClip: (clip: Clip) => void;
  onBack: () => void;
  onJobChange: (job: Job) => void;
}

const DEFAULT_PLATFORM = "youtube_shorts";

export default function Publish({ job, clips, onUpdateClip, onBack, onJobChange }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [publishingAll, setPublishingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [draftPlatform, setDraftPlatform] = useState<Record<string, string>>({});
  const [draftAccount, setDraftAccount] = useState<Record<string, string>>({});
  const [autoPublishOverrides, setAutoPublishOverrides] = useState<{
    enabled?: boolean;
    platform?: string;
    account?: string;
  }>({});
  const [posts, setPosts] = useState<PlatformPost[]>([]);
  const [doneCount, setDoneCount] = useState(0);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);

  const selected = clips.filter((c) => c.publish);

  // La plataforma con la que se creó el job es la que manda: un video generado
  // como "YouTube (video)" (horizontal, hasta 900s) no debe offered por defecto
  // como Short (vertical, 60s). Antes el destino caía en `DEFAULT_PLATFORM`
  // siempre, y por eso un video de 6 min salía como Short de 1 min.
  const jobPlatform = job.platform || job.auto_publish_platform || DEFAULT_PLATFORM;

  const autoPublish = autoPublishOverrides.enabled ?? job.auto_publish;
  // El selector de arriba manda sobre los destinos de abajo mientras el usuario
  // no los haya tocado a mano (draftPlatform solo se setea al cambiar el Select).
  const defaultTargetPlatform = autoPublishOverrides.platform || jobPlatform;
  const autoPublishPlatform = defaultTargetPlatform;
  const autoPublishAccount = autoPublishOverrides.account || job.auto_publish_account || "";

  async function refreshPosts() {
    try {
      setPosts(await getPosts(job.id));
    } catch {
      setPosts([]);
    }
  }

  async function refreshQueueStatus() {
    try {
      const status = await request<QueueStatus>(`/api/jobs/${job.id}/publish-queue`);
      setQueueStatus(status);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    void refreshPosts();
    getAccounts()
      .then((list) => {
        setAccounts(list);
        for (const clip of selected) {
          const platform = draftPlatform[clip.id] ?? defaultTargetPlatform;
          const available = accountsForPlatform(list, platform);
          if (!draftAccount[clip.id] && available[0]) {
            setDraftAccount((prev) => ({ ...prev, [clip.id]: available[0].name }));
          }
        }
      })
      .catch(() => setAccounts([]));
    refreshQueueStatus();
  }, [job.id]);

  useEffect(() => {
    const interval = setInterval(refreshQueueStatus, 5000);
    return () => clearInterval(interval);
  }, [job.id]);

  const postByDest = useMemo(() => {
    const map: Record<string, PlatformPost> = {};
    for (const p of posts) {
      const key = `${p.clip_id}|${p.platform}|${p.account ?? ""}`;
      if (key in map) continue;
      map[key] = p;
    }
    return map;
  }, [posts]);

  const destCount = useMemo(
    () => selected.reduce((acc, clip) => acc + (clip.destinations?.length ?? 0), 0),
    [selected],
  );

  function defaultDraft(clipId: string): { platform: string; account: string } {
    const platform = draftPlatform[clipId] ?? defaultTargetPlatform;
    const available = accountsForPlatform(accounts, platform);
    const account = available.some((a) => a.name === draftAccount[clipId])
      ? draftAccount[clipId]
      : available[0]?.name ?? "";
    return { platform, account };
  }

  /** Aviso honesto sobre lo que le va a pasar al clip en ese destino.
   *
   * El backend recorta al publicar (`publish_one` → `max_duration`), así que
   * publicar un clip de 6 min en Shorts lo deja en 1 min SIN avisar. Aquí se
   * dice antes de que el usuario pulse Publicar. */
  function describeMismatch(clip: Clip, platform: string): string | null {
    const label = PLATFORM_LABELS[platform] ?? platform;
    const limit = maxSecondsFor(platform);
    const notes: string[] = [];

    if (clip.duration > limit + 0.5) {
      notes.push(
        `${label} admite ${formatDuration(limit)}: se publicará recortado a ${formatDuration(limit)} de los ${formatDuration(clip.duration)} del clip.`,
      );
    }

    const isVerticalTarget = !HORIZONTAL_PLATFORMS.has(platform);
    const wasVerticalExport = clip.export_platform
      ? !HORIZONTAL_PLATFORMS.has(clip.export_platform)
      : null;
    if (clip.exported && wasVerticalExport !== null && wasVerticalExport !== isVerticalTarget) {
      notes.push(
        isVerticalTarget
          ? "El clip se exportó horizontal; al publicar aquí se re-cortará a vertical con fondo borroso."
          : "El clip se exportó vertical; al publicar aquí se quedará en vertical, no se recorta a horizontal.",
      );
    } else if (clip.exported && platform !== jobPlatform) {
      notes.push(
        `El video se creó para ${PLATFORM_LABELS[jobPlatform] ?? jobPlatform}; al publicar en ${label} se recorta con el formato de ${label}.`,
      );
    }
    return notes.length > 0 ? notes.join(" ") : null;
  }

  function changeDraftPlatform(clipId: string, platform: string) {
    setDraftPlatform((prev) => ({ ...prev, [clipId]: platform }));
    const available = accountsForPlatform(accounts, platform);
    setDraftAccount((prev) => ({ ...prev, [clipId]: available[0]?.name ?? "" }));
  }

  async function addDestination(clip: Clip) {
    const draft = defaultDraft(clip.id);
    if (!draft.platform) return;
    const newDests = [...(clip.destinations ?? []), { ...draft }];
    try {
      const updated = await updateClip(job.id, clip.id, { destinations: newDests });
      onUpdateClip(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el destino");
    }
  }

  async function removeDestination(clip: Clip, index: number) {
    const newDests = (clip.destinations ?? []).filter((_, i) => i !== index);
    try {
      const updated = await updateClip(job.id, clip.id, { destinations: newDests });
      onUpdateClip(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo quitar el destino");
    }
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
    setAutoPublishOverrides((prev) => ({ ...prev, enabled: next }));
    setError(null);
    try {
      const updated = await patchJobSettings(job.id, next, autoPublishPlatform, autoPublishAccount || null);
      onJobChange(updated);
      if (next) {
        const marked = clips.filter((c) => c.publish).length;
        if (marked > 0) {
          setSuccessMsg(`Publicando ${marked} clip${marked > 1 ? "s" : ""} marcado${marked > 1 ? "s" : ""}...`);
          let attempts = 0;
          const poll = setInterval(async () => {
            await refreshPosts();
            await refreshQueueStatus();
            attempts++;
            if (attempts >= 6) {
              clearInterval(poll);
              setSuccessMsg(`Publicaciones encoladas. Revisa la tabla de más abajo.`);
            }
          }, 3000);
        }
      } else {
        setSuccessMsg(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la configuración");
      setAutoPublishOverrides((prev) => ({ ...prev, enabled: job.auto_publish }));
    }
  }

  async function updateAutoPublishTarget(platform: string, account: string) {
    const prevPlatform = defaultTargetPlatform;
    setAutoPublishOverrides((prev) => ({ ...prev, platform, account }));
    if (prevPlatform !== platform) {
      // El destino manual hereda la plataforma de arriba SOLO en los clips donde
      // el usuario no eligió una a mano; si la eligió, se respeta su decisión
      // (es una elección deliberada, no un default olvidado).
      const touched = new Set(Object.keys(draftPlatform));
      setDraftPlatform((prev) => {
        const next = { ...prev };
        for (const clip of selected) {
          if (!touched.has(clip.id)) delete next[clip.id];
        }
        return next;
      });
      // La cuenta también hay que re-resolver: el canal de YouTube Shorts y el
      // de YouTube video son el mismo `platform` de cuenta pero distinto destino.
      const available = accountsForPlatform(accounts, platform);
      setDraftAccount((prev) => {
        const next = { ...prev };
        for (const clip of selected) {
          if (!touched.has(clip.id)) {
            next[clip.id] = available[0]?.name ?? "";
          }
        }
        return next;
      });
    }
    if (autoPublish) {
      try {
        const updated = await patchJobSettings(job.id, true, platform, account || null);
        onJobChange(updated);
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudo guardar la configuración");
      }
    }
  }

  async function publishOneDestination(clip: Clip, dest: Destination, index: number) {
    const key = `${clip.id}|${index}`;
    setBusy(key);
    setError(null);
    try {
      const post = await publishClip(job.id, clip.id, dest.platform, dest.account || null);
      if (post) setDoneCount((c) => c + 1);
      await refreshPosts();
      await refreshQueueStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo publicar el clip");
    } finally {
      setBusy(null);
    }
  }

  async function publishAllDestinations() {
    const targets = selected.flatMap((clip) =>
      (clip.destinations ?? []).map((dest) => ({ clip, dest })),
    );
    if (targets.length === 0) return;
    setPublishingAll(true);
    setError(null);
    setDoneCount(0);
    const errors: string[] = [];
    for (const { clip, dest } of targets) {
      try {
        const post = await publishClip(job.id, clip.id, dest.platform, dest.account || null);
        if (post) setDoneCount((c) => c + 1);
      } catch (err) {
        errors.push(err instanceof Error ? err.message : "Error al publicar");
      }
    }
    if (errors.length) setError(errors.join("; "));
    await refreshPosts();
    await refreshQueueStatus();
    setPublishingAll(false);
  }

  function getAccountStatusLabel(accountName: string): { label: string; color: "success" | "warning" | "error" | "default" } {
    if (!queueStatus) return { label: "Desconocido", color: "default" };
    const quotaKey = Object.keys(queueStatus.account_quotas).find(k => k.endsWith(`:${accountName}`) || k.includes(accountName));
    if (!quotaKey) return { label: "Sin cola", color: "default" };
    const quota = queueStatus.account_quotas[quotaKey];
    switch (quota.status) {
      case "healthy":
        return { label: `🟢 ${quota.uploads_today}/${6} hoy`, color: "success" };
      case "rate_limited":
        const mins = quota.next_retry ? Math.ceil((quota.next_retry - Date.now() / 1000) / 60) : 0;
        return { label: `🟡 Rate limited (${mins}m)`, color: "warning" };
      case "quota_exceeded":
        return { label: "🔴 Cuota agotada (24h)", color: "error" };
      default:
        return { label: "❓ Error", color: "error" };
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
            <Typography variant="overline" sx={{ display: "block" }}>
              Paso 4: Lo que vas a publicar
            </Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              {selected.length} {selected.length === 1 ? "clip listo" : "clips listos"}
            </Typography>
          </Box>
          <Button variant="outlined" onClick={onBack} sx={{ alignSelf: { md: "flex-end" } }}>
            Volver a REVISAR
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        {successMsg && (
          <Alert severity="success" sx={{ mt: 3 }} onClose={() => setSuccessMsg(null)}>
            {successMsg}
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
              Volver a REVISAR
            </Button>
          </Paper>
        ) : (
          <>
            <Paper sx={{ mt: 4, p: 3, bgcolor: "action.hover" }}>
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
                    sx={{ fontFamily: MONO, fontSize: "0.72rem" }}
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

            <Paper sx={{ mt: 4, p: 3 }}>
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
                    Al activarla, cada clip que marques en el carrete se exporta y publica
                    automáticamente al destino que elijas.
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
              {autoPublish && (
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1.5}
                  sx={{ mt: 2, pt: 2, borderTop: "1px dashed", borderColor: "divider", alignItems: { xs: "stretch", sm: "center" } }}
                >
                  <Box sx={{ minWidth: 80 }}>
                    <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.72rem", fontWeight: 600 }}>
                      Plataforma
                    </Typography>
                    <Select
                      size="small"
                      value={autoPublishPlatform}
                      onChange={(e) => void updateAutoPublishTarget(e.target.value, autoPublishAccount)}
                      sx={{ minWidth: 170, mt: 0.25 }}
                    >
                      {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                        <MenuItem key={value} value={value}>
                          {label}
                        </MenuItem>
                      ))}
                    </Select>
                  </Box>
                  <Box sx={{ minWidth: 190 }}>
                    <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.72rem", fontWeight: 600 }}>
                      Canal de publicación
                    </Typography>
                    <Select
                      size="small"
                      value={autoPublishAccount}
                      onChange={(e) => void updateAutoPublishTarget(autoPublishPlatform, e.target.value)}
                      sx={{ minWidth: 190, mt: 0.25 }}
                    >
                      <MenuItem value="">— sin canal —</MenuItem>
                      {accountsForPlatform(accounts, autoPublishPlatform).map((a) => (
                        <MenuItem key={a.id} value={a.name}>
                          {a.name}
                          {a.handle ? ` (${a.handle})` : ""}
                        </MenuItem>
                      ))}
                    </Select>
                    {accountsForPlatform(accounts, autoPublishPlatform).length === 0 && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block", fontSize: "0.68rem" }}>
                        No hay canales vinculados para esta plataforma. Ve a CUENTAS para vincular uno.
                      </Typography>
                    )}
                  </Box>
                </Stack>
              )}
            </Paper>

            {queueStatus && (
              <Paper sx={{ mt: 2, p: 2, bgcolor: "action.hover" }}>
                <Typography variant="overline" sx={{ display: "block" }}>Estado de cola de publicación</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1 }}>
                  {queueStatus.pending} tareas pendientes. Las cuentas rotan automáticamente al agotar cuota.
                </Typography>
                <Box sx={{ overflowX: "auto" }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Cuenta</TableCell>
                        <TableCell>Plataforma</TableCell>
                        <TableCell>Estado</TableCell>
                        <TableCell>Subidas hoy</TableCell>
                        <TableCell>Próximo reintento</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {Object.entries(queueStatus.account_quotas).map(([key, quota]) => {
                        const [platform, account] = key.split(":");
                        return (
                          <TableRow key={key}>
                            <TableCell sx={{ fontWeight: 600 }}>{account}</TableCell>
                            <TableCell>{PLATFORM_LABELS[platform] ?? platform}</TableCell>
                            <TableCell>
                              <Chip
                                size="small"
                                label={quota.status === "healthy" ? "🟢 Activa" : quota.status === "rate_limited" ? "🟡 Esperando" : "🔴 Bloqueada"}
                                variant={quota.status === "healthy" ? "filled" : "outlined"}
                                sx={{
                                  bgcolor: quota.status === "healthy" ? "rgba(30,122,70,.08)" : quota.status === "rate_limited" ? "rgba(255,198,71,.15)" : "rgba(196,61,61,.08)",
                                  color: quota.status === "healthy" ? "#1E7A46" : quota.status === "rate_limited" ? ON_ACCENT : "#C43D3D",
                                }}
                              />
                            </TableCell>
                            <TableCell>{quota.uploads_today}/6</TableCell>
                            <TableCell>
                              {quota.next_retry
                                ? `${Math.ceil((quota.next_retry - Date.now() / 1000) / 60)} min`
                                : quota.quota_reset
                                ? `${Math.ceil((quota.quota_reset - Date.now() / 1000) / 60 / 60)} h`
                                : "—"}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </Box>
              </Paper>
            )}

            <Stack spacing={3} sx={{ mt: 3 }}>
              {selected.map((clip) => {
                const clipDests = clip.destinations ?? [];
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
                          fontFamily: MONO,
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
                        <Box sx={{ flex: 1 }}>
                          <Typography variant="h5">{clip.title}</Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            "{clip.line}"
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1}>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => void togglePublish(clip, !clip.publish)}
                            disabled={busy === clip.id || publishingAll}
                            startIcon={
                              busy === clip.id ? (
                                <CircularProgress size={14} color="inherit" />
                              ) : undefined
                            }
                            sx={{ whiteSpace: "nowrap", color: "text.secondary" }}
                          >
                            Quitar de la lista
                          </Button>
                        </Stack>
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
                            const post = postByDest[`${clip.id}|${dest.platform}|${dest.account}`];
                            const key = `${clip.id}|${index}`;
                            const busyHere = busy === key;
                            const accountStatus = getAccountStatusLabel(dest.account);
                            const mismatch = describeMismatch(clip, dest.platform);
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
                                          color: post.status === "publicado" ? ON_ACCENT : undefined,
                                          borderColor: post.status === "publicado" ? MARK : undefined,
                                        }}
                                        label={POST_STATUS_LABELS[post.status] ?? post.status}
                                      />
                                    )}
                                    <Chip
                                      size="small"
                                      label={accountStatus.label}
                                      variant="outlined"
                                      sx={{
                                        bgcolor: accountStatus.color === "success" ? "rgba(30,122,70,.08)" : accountStatus.color === "warning" ? "rgba(255,198,71,.15)" : "rgba(196,61,61,.08)",
                                        color: accountStatus.color === "success" ? "#1E7A46" : accountStatus.color === "warning" ? ON_ACCENT : "#C43D3D",
                                        fontSize: "0.58rem",
                                      }}
                                    />
                                  </Stack>
                                  {mismatch && (
                                    <Alert
                                      severity="warning"
                                      sx={{
                                        mt: 1,
                                        py: 0.25,
                                        fontSize: "0.7rem",
                                        alignItems: "center",
                                      }}
                                    >
                                      {mismatch}
                                    </Alert>
                                  )}
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
                                      onClick={() => void removeDestination(clip, index)}
                                      disabled={publishingAll}
                                    >
                                      <CloseRoundedIcon fontSize="small" />
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