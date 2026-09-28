import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  brandingAvatarUrl,
  brandingBannerUrl,
  generateBranding,
  getBranding,
} from "../api";
import type { BrandingInfo } from "../api";
import { EDGE, MARK, MONO } from "../theme";

export default function Branding() {
  const [info, setInfo] = useState<BrandingInfo | null>(null);
  const [channelName, setChannelName] = useState("FUTBOL VIRAL EDITS");
  const [tagline, setTagline] = useState("Resúmenes virales de fútbol");
  const [backgroundUrl, setBackgroundUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    getBranding()
      .then((b) => {
        setInfo(b);
        if (b.channel_name) setChannelName(b.channel_name);
        if (b.tagline) setTagline(b.tagline);
        if (b.background_url) setBackgroundUrl(b.background_url);
      })
      .catch(() => {});
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrorMsg(null);
    try {
      const b = await generateBranding({
        channel_name: channelName.trim() || "FUTBOL VIRAL EDITS",
        tagline: tagline.trim(),
        background_url: backgroundUrl.trim() || null,
      });
      setInfo(b);
      window.dispatchEvent(new CustomEvent("edgetape:branding", { detail: b }));
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo generar la marca del canal");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper sx={{ mt: 5, p: { xs: 3, md: 4 } }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { md: "flex-end" }, justifyContent: "space-between" }}>
        <Box>
          <Typography variant="overline">Tu identidad en YouTube</Typography>
          <Typography variant="h5" sx={{ mt: 0.5 }}>
            Marca del canal
          </Typography>
        </Box>
        <Chip
          size="small"
          variant="outlined"
          label={info?.banner_exists && info?.avatar_exists ? "generada" : "pendiente"}
          sx={{ alignSelf: "flex-start" }}
        />
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "62ch" }}>
        Genera el <b>banner (2560x1440)</b> y la <b>imagen de perfil (800x800)</b> de tu canal
        con la identidad de la app. Puedes usar una foto de fondo (URL) y el sistema la escala
        y le superpone tu nombre; si la URL no responde, usa un fondo gradiente azul.
      </Typography>

      <Box component="form" onSubmit={onSubmit} sx={{ mt: 3 }}>
        <Stack spacing={2}>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>
            <TextField
              label="Nombre del canal"
              value={channelName}
              onChange={(e) => setChannelName(e.target.value)}
              required
            />
            <TextField
              label="Tagline (debajo del nombre)"
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              slotProps={{ htmlInput: { maxLength: 60 } }}
            />
          </Box>
          <TextField
            label="URL de fondo (opcional)"
            placeholder="https://…/foto-de-futbol.jpg"
            value={backgroundUrl}
            onChange={(e) => setBackgroundUrl(e.target.value)}
            helperText="Cualquier imagen http(s). Si no se puede descargar, se usa un fondo azul por defecto."
            slotProps={{ htmlInput: { spellCheck: false } }}
          />
          <Button variant="contained" type="submit" disabled={busy} sx={{ alignSelf: "flex-start" }}>
            {busy ? "Generando…" : info?.banner_exists ? "Regenerar marca" : "Generar banner y avatar"}
          </Button>
        </Stack>
      </Box>

      {errorMsg && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {errorMsg}
        </Alert>
      )}

      {(info?.banner_exists || info?.avatar_exists) && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="overline" sx={{ display: "block", color: EDGE }}>
            Vista previa
          </Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr auto" }, gap: 3, alignItems: "start", mt: 1.5 }}>
            <Stack spacing={1}>
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO }}>
                Banner · 2560x1440
              </Typography>
              <Box
                component="img"
                src={brandingBannerUrl()}
                alt="Banner del canal"
                sx={{
                  width: "100%",
                  maxWidth: 720,
                  aspectRatio: "16/9",
                  objectFit: "cover",
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  boxShadow: "0 2px 8px rgba(20,22,26,.1)",
                }}
              />
            </Stack>
            <Stack spacing={1} sx={{ alignItems: { xs: "flex-start", md: "center" } }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO }}>
                Avatar · 800x800
              </Typography>
              <Box
                component="img"
                src={brandingAvatarUrl()}
                alt="Avatar del canal"
                sx={{
                  width: 160,
                  height: 160,
                  borderRadius: "50%",
                  objectFit: "cover",
                  border: "3px solid",
                  borderColor: MARK,
                  boxShadow: "0 2px 10px rgba(20,22,26,.15)",
                }}
              />
            </Stack>
          </Box>
          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap" }}>
            <Button
              size="small"
              variant="outlined"
              href={brandingBannerUrl()}
              download="banner.jpg"
              sx={{ borderColor: "divider" }}
            >
              descargar banner
            </Button>
            <Button
              size="small"
              variant="outlined"
              href={brandingAvatarUrl()}
              download="avatar.png"
              sx={{ borderColor: "divider" }}
            >
              descargar avatar
            </Button>
          </Stack>
          <Alert severity="info" sx={{ mt: 3 }}>
            Sube estas imágenes en <b>YouTube Studio → Personalización → Marca</b>: el banner debe
            verse bien en su zona segura (texto centrado) y el avatar se recorta en círculo.
          </Alert>
        </Box>
      )}
    </Paper>
  );
}