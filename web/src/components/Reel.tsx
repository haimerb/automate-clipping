import { useState } from "react";
import { Box, Button, Container, Grid, Paper, Stack, Typography } from "@mui/material";
import ClipCard from "./ClipCard";
import ClipPreview from "./ClipPreview";
import BarWave from "./BarWave";
import MonetizationPanel from "./MonetizationPanel";
import {
  downloadUrl,
  exportClip,
  formatDuration,
  formatTimecode,
  setClipPublish,
} from "../api";
import type { Clip, Job } from "../api";
import { EDGE, INK, MARK } from "../theme";

interface Props {
  job: Job;
  clips: Clip[];
  onUpdateClip: (clip: Clip) => void;
  onGoPublish: () => void;
  onReset: () => void;
  onDashboard: () => void;
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
  onGoPublish,
  onReset,
  onDashboard,
}: Props) {
  const [selected, setSelected] = useState<Clip | null>(clips[0] ?? null);
  const [busy, setBusy] = useState<string | null>(null);

  const selectedClip = selected ? clips.find((c) => c.id === selected.id) ?? selected : null;
  const toPublish = clips.filter((c) => c.publish).length;
  const fuente = job.source === "youtube" ? "YouTube" : "archivo";

  async function onExport(clip: Clip) {
    setBusy(clip.id);
    try {
      const updated = await exportClip(job.id, clip.id);
      onUpdateClip(updated);
      setSelected(updated);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Falló la exportación");
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
      window.alert(err instanceof Error ? err.message : "No se pudo marcar el clip");
    } finally {
      setBusy(null);
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
            <Typography variant="overline">Sección 02 — el carrete</Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              Tus clips, ordenados
            </Typography>
          </Box>
          <Stack spacing={0.5} sx={{ alignItems: { xs: "flex-start", md: "flex-end" } }}>
            <Typography variant="body2" color="text.secondary">
              Detectado automáticamente desde <b>{job.filename}</b>
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {job.clip_count} clips · {job.duration ? formatDuration(job.duration) : "?"} de fuente
              ({fuente}) · {job.transcriber}
              {job.scorer ? ` · ${job.scorer}` : ""}
            </Typography>
            <Button
              variant="contained"
              onClick={onGoPublish}
              disabled={toPublish === 0}
              sx={{ mt: 1 }}
            >
              {toPublish === 0
                ? "Marca clips para publicar"
                : `Publicar ${toPublish} ${toPublish === 1 ? "clip" : "clips"}`}
            </Button>
          </Stack>
        </Stack>
      </Container>

      <Box
        aria-hidden
        sx={{
          height: 16,
          my: 3,
          background: `repeating-radial-gradient(circle at 8px 8px, ${INK} 0 2.5px, transparent 3px)`,
          backgroundSize: "22px 16px",
          opacity: 0.18,
        }}
      />

      <Container maxWidth="lg">
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
                gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" },
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
                        <Stack
                          direction={{ xs: "column", sm: "row" }}
                          spacing={2}
                          sx={{ justifyContent: "space-between" }}
                        >
                          <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap" }}>
                            <Typography sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                              EN<b style={{ color: EDGE }}> {formatTimecode(selectedClip.start)}</b>
                            </Typography>
                            <Typography sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                              SAL<b style={{ color: EDGE }}> {formatTimecode(selectedClip.end)}</b>
                            </Typography>
                            <Typography sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                              DUR<b style={{ color: EDGE }}> {formatDuration(selectedClip.duration)}</b>
                            </Typography>
                          </Stack>
                        </Stack>

                        <Box>
                          <Typography variant="h5">{selectedClip.title}</Typography>
                          <Typography
                            variant="body1"
                            sx={{
                              mt: 1,
                              color: "text.secondary",
                              "& mark": { background: MARK, color: INK, padding: "0 3px" },
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

                <MonetizationPanel jobId={job.id} clip={selectedClip} />
              </>
            )}
          </>
        )}
      </Container>

      <Box sx={{ mt: 8, borderTop: "1px solid", borderColor: "divider" }}>
        <Container maxWidth="lg" sx={{ py: 5, textAlign: "center" }}>
          <Typography variant="h5" sx={{ maxWidth: "24ch", mx: "auto" }}>
            Nunca vuelvas a escuchar una grabación de dos horas <em>entera</em>.
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 3 }}>
            Edgetape hace el escaneo, tú tomas la decisión. Lleva lo mejor a tu feed en minutos.
          </Typography>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1.5}
            sx={{ justifyContent: "center" }}
          >
            <Button variant="contained" onClick={onGoPublish} disabled={toPublish === 0}>
              {toPublish === 0 ? "Marca clips para publicar" : `Publicar ${toPublish} clips`}
            </Button>
            <Button variant="outlined" onClick={onDashboard}>
              Ver panel de ganancias
            </Button>
            <Button onClick={onReset}>Procesar otra grabación</Button>
          </Stack>
        </Container>
      </Box>
    </Box>
  );
}
