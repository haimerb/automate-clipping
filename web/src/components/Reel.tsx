import { useState } from "react";
import { Box, Button, Chip, Container, Grid, Paper, Stack, Typography } from "@mui/material";
import ClipCard from "./ClipCard";
import ClipPreview from "./ClipPreview";
import BarWave from "./BarWave";
import MonetizationPanel from "./MonetizationPanel";
import ConfirmDialog from "./ConfirmDialog";
import {
  deleteJobMedia,
  downloadUrl,
  exportClip,
  formatDuration,
  formatTimecode,
  regenerateJob,
  reprocessJob,
  setClipPublish,
} from "../api";
import type { Clip, Job } from "../api";
import { EDGE, MARK, MONO, ON_ACCENT, SURFACE_2 } from "../theme";

interface Props {
  job: Job;
  clips: Clip[];
  onUpdateClip: (clip: Clip) => void;
  onGoReview: () => void;
  onReset: () => void;
  onDashboard: () => void;
  onRegenerated?: () => void;
}

function highlight(script: string, line: string): string {
  const idx = script.toLowerCase().indexOf(line.toLowerCase());
  if (idx === -1) return script;
  const marked = script.slice(idx, idx + line.length);
  return `${script.slice(0, idx)}<mark>${marked}</mark>${script.slice(idx + line.length)}`;
}

export default function Reel({
  job,
  clips,
  onUpdateClip,
  onGoReview,
  onReset,
  onDashboard,
  onRegenerated,
}: Props) {
  const [selected, setSelected] = useState<Clip | null>(clips[0] ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [askRegenerate, setAskRegenerate] = useState(false);
  const [askFree, setAskFree] = useState(false);
  const [freed, setFreed] = useState<string | null>(null);
  const [errorDialog, setErrorDialog] = useState<string | null>(null);
  const esIA = job.source === "generate";

  const selectedClip = selected ? clips.find((c) => c.id === selected.id) ?? selected : null;
  const toPublish = clips.filter((c) => c.publish).length;
  const fuente = job.source === "youtube" || job.source === "url" ? "enlace" : "archivo";

  async function onRegenerate() {
    setRegenerating(true);
    setAskRegenerate(false);
    try {
      await regenerateJob(job.id);
      onRegenerated?.();
    } catch (err) {
      setErrorDialog(err instanceof Error ? err.message : "No se pudo regenerar el video");
    } finally {
      setRegenerating(false);
    }
  }

  async function onFreeSpace() {
    setAskFree(false);
    try {
      const res = await deleteJobMedia(job.id);
      const mb = res.freed_bytes / (1024 * 1024);
      setFreed(mb >= 1 ? `Liberaste ${mb.toFixed(1)} MB de disco` : `Liberaste ${(res.freed_bytes / 1024).toFixed(0)} KB de disco`);
    } catch (err) {
      setErrorDialog(err instanceof Error ? err.message : "No se pudo liberar el espacio");
    }
  }

  async function onExport(clip: Clip) {
    setBusy(clip.id);
    try {
      const updated = await exportClip(job.id, clip.id);
      onUpdateClip(updated);
      setSelected(updated);
    } catch (err) {
      setErrorDialog(err instanceof Error ? err.message : "Falló la exportación");
    } finally {
      setBusy(null);
    }
  }

  async function onTogglePublish(clip: Clip, publish: boolean) {
    setBusy(clip.id);
    try {
      const updated = await setClipPublish(job.id, clip.id, publish);
      onUpdateClip(updated);
    } catch (err) {
      setErrorDialog(err instanceof Error ? err.message : "No se pudo marcar el clip");
    } finally {
      setBusy(null);
    }
  }

  async function onReprocess() {
    setReprocessing(true);
    try {
      const updated = await reprocessJob(job.id);
      for (const c of updated) onUpdateClip(c);
    } catch (err) {
      setErrorDialog(err instanceof Error ? err.message : "No se pudo regenerar la metadata");
    } finally {
      setReprocessing(false);
    }
  }

  return (
    <Box component="section">
        <Container maxWidth="lg" sx={{ py: { xs: 5, md: 7 } }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" }, mb: 2 }}
        >
          <Box>
            <Typography variant="overline" sx={{ display: "block" }}>
              El carrete
            </Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              Tus clips, ordenados
            </Typography>
          </Box>
          <Stack
            direction="row"
            spacing={1}
            sx={{ flexWrap: "wrap", justifyContent: { xs: "flex-start", md: "flex-end" } }}
          >
            <Chip size="small" variant="outlined" label={`${job.clip_count} clips`} />
            <Chip
              size="small"
              variant="outlined"
              label={job.duration ? `${formatDuration(job.duration)} de fuente` : "fuente: ?"}
            />
            <Chip size="small" variant="outlined" label={`${fuente} · ${job.transcriber}`} />
            {job.scorer ? <Chip size="small" variant="outlined" label={job.scorer} /> : null}
          </Stack>
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Detectado automáticamente desde <b>{job.filename}</b>. Toca un clip para revisarlo en
          detalle. Marca los que quieras publicar y continua a <b>REVISAR</b>.
        </Typography>

        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", sm: "center" }, mb: 3 }}
        >
          <Button variant="outlined" onClick={onDashboard} sx={{ alignSelf: { xs: "stretch", sm: "flex-start" } }}>
            Ver panel de ganancias
          </Button>
          <Button
            variant="outlined"
            onClick={() => void onReprocess()}
            disabled={reprocessing}
            sx={{ alignSelf: { xs: "stretch", sm: "flex-start" } }}
          >
            {reprocessing ? "Regenerando…" : "Regenerar metadata"}
          </Button>
          {esIA && (
            <Button
              variant="outlined"
              onClick={() => setAskRegenerate(true)}
              disabled={regenerating}
              sx={{ alignSelf: { xs: "stretch", sm: "flex-start" } }}
            >
              {regenerating ? "Renderizando…" : "Regenerar video con IA"}
            </Button>
          )}
          <Button
            variant="contained"
            onClick={onGoReview}
            disabled={toPublish === 0}
            sx={{ alignSelf: { xs: "stretch", sm: "flex-end" } }}
          >
            {toPublish === 0
              ? "Marca clips para continuar"
              : `Continuar a REVISAR (${toPublish} ${toPublish === 1 ? "clip" : "clips"}) →`}
          </Button>
        </Stack>
      </Container>

      <Box aria-hidden sx={{ height: 14, background: `repeating-linear-gradient(to right, var(--mui-palette-text-secondary) 0 12px, transparent 12px 26px)`, opacity: 0.85 }} />

      <Box sx={{ bgcolor: SURFACE_2, borderTop: "1px solid", borderBottom: "1px solid", borderColor: "divider" }}>
      <Container maxWidth="lg" sx={{ py: { xs: 5, md: 7 } }}>
          {clips.length === 0 ? (
            <Paper sx={{ p: 5, textAlign: "center", borderStyle: "dashed" }}>
              <Typography variant="h6">No se encontraron clips</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 2 }}>
                No encontramos pasajes suficientemente fuertes para cortar. Prueba con una grabación
                más larga o con más energía.
              </Typography>
              <Button variant="outlined" onClick={onReset}>
                Probar otra grabación
              </Button>
            </Paper>
          ) : (
            <>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", md: "repeat(3, 1fr)" },
                  gap: 3,
                  "& > *:nth-of-type(3n+2)": {
                    transform: { sm: "rotate(-0.35deg) translateY(3px)" },
                  },
                  "& > *:nth-of-type(3n+3)": {
                    transform: { sm: "rotate(0.4deg) translateY(1px)" },
                  },
                }}
              >
                {clips.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    jobId={job.id}
                    clip={clip}
                    active={clip.id === selectedClip?.id}
                    onSelect={setSelected}
                    onTogglePublish={(c, p) => void onTogglePublish(c, p)}
                  />
                ))}
              </Box>

              {selectedClip && (
                <>
                  <Paper sx={{ mt: 5, p: { xs: 2, md: 3 } }}>
                    <Grid container spacing={3} sx={{ alignItems: "flex-start" }}>
                      <Grid size={{ xs: 12, md: 4 }}>
                        <ClipPreview
                          jobId={job.id}
                          clip={selectedClip}
                          variant="player"
                          showTimecode
                          showExport
                        />
                        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                          {selectedClip.exported && selectedClip.export_name ? (
                            <Button
                              variant="contained"
                              href={downloadUrl(job.id, selectedClip.id)}
                              download={selectedClip.export_name}
                              sx={{ flex: 1 }}
                            >
                              Descargar
                            </Button>
                          ) : (
                            <Button
                              variant="contained"
                              onClick={() => void onExport(selectedClip)}
                              disabled={busy !== null}
                              sx={{ flex: 1 }}
                            >
                              {busy === selectedClip.id ? "Cortando…" : "Cortar y exportar"}
                            </Button>
                          )}
                        </Stack>
                      </Grid>

                      <Grid size={{ xs: 12, md: 8 }}>
                        <Stack spacing={2.5}>
                          <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap" }}>
                            <Box>
                              <Typography variant="overline" sx={{ display: "block", fontSize: "0.56rem" }}>
                                Entrada
                              </Typography>
                              <Typography sx={{ fontFamily: MONO, fontSize: "0.9rem", color: EDGE, fontWeight: 600 }}>
                                {formatTimecode(selectedClip.start)}
                              </Typography>
                            </Box>
                            <Box>
                              <Typography variant="overline" sx={{ display: "block", fontSize: "0.56rem" }}>
                                Salida
                              </Typography>
                              <Typography sx={{ fontFamily: MONO, fontSize: "0.9rem", color: EDGE, fontWeight: 600 }}>
                                {formatTimecode(selectedClip.end)}
                              </Typography>
                            </Box>
                            <Box>
                              <Typography variant="overline" sx={{ display: "block", fontSize: "0.56rem" }}>
                                Duración
                              </Typography>
                              <Typography sx={{ fontFamily: MONO, fontSize: "0.9rem", color: EDGE, fontWeight: 600 }}>
                                {formatDuration(selectedClip.duration)}
                              </Typography>
                            </Box>
                          </Stack>

                          <Box>
                            <Typography variant="h5">{selectedClip.title}</Typography>
                            <Typography
                              variant="body1"
                              sx={{
                                mt: 1,
                                color: "text.secondary",
                                "& mark": { background: MARK, color: ON_ACCENT, padding: "0 3px" },
                              }}
                              dangerouslySetInnerHTML={{
                                __html: highlight(selectedClip.script, selectedClip.line),
                              }}
                            />
                            <Box sx={{ mt: 2 }}>
                              <BarWave seed={`detail-${selectedClip.id}`} />
                            </Box>
                          </Box>
                        </Stack>
                      </Grid>
                    </Grid>
                  </Paper>

                  <Box sx={{ mt: 4 }}>
                    <MonetizationPanel jobId={job.id} clip={selectedClip} />
                  </Box>
                </>
              )}
            </>
          )}
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Stack direction="row" spacing={1.5} sx={{ justifyContent: "center", flexWrap: "wrap" }}>
          <Button variant="contained" onClick={onGoReview} disabled={toPublish === 0}>
            {toPublish === 0 ? "Marca clips para continuar" : `Continuar a REVISAR (${toPublish} clips)`}
          </Button>
          <Button
            variant="outlined"
            onClick={() => void onReprocess()}
            disabled={reprocessing}
          >
            {reprocessing ? "Regenerando…" : "Regenerar metadata"}
          </Button>
          {esIA && (
            <Button
              variant="outlined"
              onClick={() => setAskRegenerate(true)}
              disabled={regenerating}
            >
              {regenerating ? "Renderizando…" : "Regenerar video con IA"}
            </Button>
          )}
          <Button variant="outlined" onClick={() => setAskFree(true)}>
            Liberar espacio en disco
          </Button>
          <Button variant="outlined" onClick={onDashboard}>
            Ver panel de ganancias
          </Button>
          <Button onClick={onReset}>Procesar otra grabación</Button>
        </Stack>
        {freed && (
          <Typography
            variant="body2"
            sx={{ mt: 2, textAlign: "center", color: "text.secondary" }}
          >
            {freed}. El job sigue en el panel y puedes volver a generarlo cuando quieras.
          </Typography>
        )}
      </Container>
      <ConfirmDialog
        open={askRegenerate}
        title="Regenerar el video"
        message="Se va a renderizar de nuevo con el motor actual (b-roll de stock, música y guion nuevos). La versión anterior se guarda en previous/ por si el resultado es peor. Los clips y las publicaciones registradas se conservan."
        confirmLabel="Regenerar"
        cancelLabel="Cancelar"
        severity="warning"
        onConfirm={() => void onRegenerate()}
        onCancel={() => setAskRegenerate(false)}
      />
      <ConfirmDialog
        open={askFree}
        title="Liberar espacio"
        message="Se borran el video de origen, los clips exportados y las versiones previas. El job sigue listado con sus clips y publicaciones, pero ocupa mucho menos disco."
        confirmLabel="Liberar"
        cancelLabel="Cancelar"
        severity="warning"
        onConfirm={() => void onFreeSpace()}
        onCancel={() => setAskFree(false)}
      />
      <ConfirmDialog
        open={errorDialog !== null}
        title="Error"
        message={errorDialog ?? ""}
        confirmLabel="Entendido"
        cancelLabel=""
        severity="error"
        onConfirm={() => setErrorDialog(null)}
        onCancel={() => setErrorDialog(null)}
      />
    </Box>
  );
}