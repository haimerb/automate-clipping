import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import { formatDuration, formatTimecode, setClipPublish, updateClipMetadata } from "../api";
import type { Clip, Job } from "../api";
import ClipPreview from "./ClipPreview";
import ThumbnailPicker from "./ThumbnailPicker";
import MonetizationPanel from "./MonetizationPanel";
import { MONO, ON_ACCENT } from "../theme";

interface Props {
  job: Job;
  clips: Clip[];
  onUpdateClip: (clip: Clip) => void;
  onBack: () => void;
  onNext: () => void;
}

export default function Review({ job, clips, onUpdateClip, onBack, onNext }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingClip, setEditingClip] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editTags, setEditTags] = useState("");

  const selected = clips.filter((c) => c.publish);

  function startEditMetadata(clip: Clip) {
    setEditingClip(clip.id);
    setEditTitle(clip.title);
    setEditDescription(clip.description);
    setEditTags(clip.tags.join(", "));
  }

  async function saveMetadata(clipId: string) {
    try {
      const tags = editTags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await updateClipMetadata(job.id, clipId, {
        title: editTitle,
        description: editDescription,
        tags,
      });
      onUpdateClip(updated);
      setEditingClip(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la metadata");
    }
  }

  async function togglePublish(clip: Clip, publish: boolean) {
    setBusy(clip.id);
    setError(null);
    try {
      const updated = await setClipPublish(job.id, clip.id, publish);
      onUpdateClip(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar el clip");
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
            <Typography variant="overline" sx={{ display: "block" }}>
              Paso 3: Revisar y pulir
            </Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              {selected.length} {selected.length === 1 ? "clip para publicar" : "clips para publicar"}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "62ch" }}>
              Revisa el gancho, edita el título, la descripción y los tags, y elige la miniatura
              más vendedora para cada clip.
            </Typography>
          </Box>
          <Button variant="outlined" onClick={onBack} sx={{ alignSelf: { md: "flex-end" } }}>
            Volver a CLIPS
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        {selected.length === 0 ? (
          <Paper sx={{ mt: 4, p: 5, textAlign: "center", borderStyle: "dashed" }}>
            <Typography variant="h6">Nada seleccionado para revisar</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 2 }}>
              Vuelve al carrete y marca los clips con el indicador <b>para publicar</b> para
              afinarlos aquí.
            </Typography>
            <Button variant="contained" onClick={onBack}>
              Elegir clips
            </Button>
          </Paper>
        ) : (
          <>
            <Stack spacing={3} sx={{ mt: 4 }}>
              {selected.map((clip) => {
                const isEditing = editingClip === clip.id;
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
                      <ClipPreview jobId={job.id} clip={clip} variant="player" showTimecode />
                      <Typography
                        sx={{
                          mt: 1,
                          fontFamily: MONO,
                          fontSize: "0.66rem",
                          color: "text.secondary",
                        }}
                      >
                        {formatTimecode(clip.start)} → {formatTimecode(clip.end)} ·{" "}
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
                          {isEditing ? (
                            <TextField
                              size="small"
                              fullWidth
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              label="Título"
                              slotProps={{ htmlInput: { maxLength: 100 } }}
                              sx={{ mb: 1 }}
                            />
                          ) : (
                            <Typography variant="h5">{clip.title}</Typography>
                          )}
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            "{clip.line}"
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1}>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() =>
                              isEditing ? setEditingClip(null) : startEditMetadata(clip)
                            }
                            startIcon={isEditing ? undefined : <EditRoundedIcon />}
                            sx={{ whiteSpace: "nowrap" }}
                          >
                            {isEditing ? "Cancelar" : "Editar"}
                          </Button>
                          <Button
                            size="small"
                            variant={clip.publish ? "contained" : "outlined"}
                            color={clip.publish ? "secondary" : "primary"}
                            onClick={() => void togglePublish(clip, !clip.publish)}
                            disabled={busy === clip.id}
                            startIcon={
                              busy === clip.id ? (
                                <CircularProgress size={14} color="inherit" />
                              ) : undefined
                            }
                            sx={{ whiteSpace: "nowrap", color: clip.publish ? ON_ACCENT : undefined }}
                          >
                            {clip.publish ? "✔ Para publicar" : "No publicar"}
                          </Button>
                        </Stack>
                      </Stack>

                      {isEditing && (
                        <Box sx={{ mt: 2, p: 2, bgcolor: "action.hover", borderRadius: 1 }}>
                          <TextField
                            size="small"
                            fullWidth
                            multiline
                            rows={3}
                            value={editDescription}
                            onChange={(e) => setEditDescription(e.target.value)}
                            label="Descripción"
                            slotProps={{ htmlInput: { maxLength: 2000 } }}
                            sx={{ mb: 1 }}
                          />
                          <TextField
                            size="small"
                            fullWidth
                            value={editTags}
                            onChange={(e) => setEditTags(e.target.value)}
                            label="Tags (separados por coma)"
                            helperText={`${editTags.split(",").filter((t) => t.trim()).length} tags`}
                            sx={{ mb: 1 }}
                          />
                          <Button
                            size="small"
                            variant="contained"
                            onClick={() => void saveMetadata(clip.id)}
                          >
                            Guardar cambios
                          </Button>
                        </Box>
                      )}

                      <Box
                        sx={{
                          mt: 2,
                          borderTop: "1px dashed",
                          borderColor: "divider",
                          pt: 2,
                        }}
                      >
                        <ThumbnailPicker jobId={job.id} clip={clip} onUpdateClip={onUpdateClip} />
                      </Box>

                      <Box sx={{ mt: 2, borderTop: "1px dashed", borderColor: "divider", pt: 2 }}>
                        <MonetizationPanel jobId={job.id} clip={clip} />
                      </Box>
                    </Box>
                  </Paper>
                );
              })}
            </Stack>

            <Paper
              sx={{
                mt: 4,
                p: 3,
                display: "flex",
                flexDirection: { xs: "column", sm: "row" },
                gap: 2,
                alignItems: { xs: "stretch", sm: "center" },
                justifyContent: "space-between",
              }}
            >
              <Box>
                <Typography variant="overline" sx={{ display: "block" }}>
                  Siguiente paso
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Configura los destinos (plataforma + canal) y publica o lanza el envío en bloque.
                </Typography>
              </Box>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <Button variant="outlined" onClick={onBack}>
                  Volver a CLIPS
                </Button>
                <Button
                  variant="contained"
                  color="secondary"
                  onClick={onNext}
                  disabled={selected.length === 0}
                  sx={{ color: ON_ACCENT }}
                >
                  Continuar a PUBLICAR ({selected.length}) →
                </Button>
              </Stack>
            </Paper>
          </>
        )}
      </Container>
    </Box>
  );
}