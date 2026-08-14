import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  ACCOUNT_PLATFORM_LABELS,
  createAccount,
  deleteAccount,
  getAccounts,
  getYoutubeAuthUrl,
  updateAccount,
} from "../api";
import type { AccountInput, LinkedAccount } from "../api";
import { EDGE, MARK } from "../theme";

const EMPTY: AccountInput = {
  platform: "youtube",
  name: "",
  handle: "",
  token: "",
  client_id: "",
  client_secret: "",
  redirect_uri: "",
};

interface FormState extends AccountInput {
  client_secret: string;
  redirect_uri: string;
}

export default function Accounts() {
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [editing, setEditing] = useState<LinkedAccount | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY as FormState);
  const [busy, setBusy] = useState(false);
  const [connectBusy, setConnectBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setAccounts(await getAccounts());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las cuentas");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (window.location.search.includes("youtube=connected")) {
      void refresh();
      window.history.replaceState({}, "", window.location.pathname);
      window.alert("YouTube conectado. Ya puedes publicar clips desde edgetape.");
    } else if (window.location.search.includes("youtube=error")) {
      window.history.replaceState({}, "", window.location.pathname);
      window.alert("No se pudo conectar YouTube. Revisa las credenciales y el token en la terminal del servidor.");
    }
  }, []);

  async function connectYoutube(account: LinkedAccount) {
    setConnectBusy(account.id);
    setError(null);
    try {
      const { auth_url } = await getYoutubeAuthUrl(account.id);
      window.location.href = auth_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar la conexión");
      setConnectBusy(null);
    }
  }

  function startAdd() {
    setEditing(null);
    setForm(EMPTY as FormState);
    setShowForm(true);
  }

  function startEdit(account: LinkedAccount) {
    setEditing(account);
    setForm({
      platform: account.platform,
      name: account.name,
      handle: account.handle,
      token: account.token ?? "",
      client_id: account.client_id ?? "",
      client_secret: "",
      redirect_uri: account.redirect_uri ?? "",
    });
    setShowForm(true);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const input: AccountInput = {
        platform: form.platform,
        name: form.name.trim(),
        handle: form.handle.trim(),
        token: form.token?.trim() || null,
        client_id: form.client_id?.trim() || null,
        client_secret: form.client_secret.trim() || null,
        redirect_uri: form.redirect_uri?.trim() || null,
      };
      if (editing) await updateAccount(editing.id, input);
      else await createAccount(input);
      setShowForm(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(account: LinkedAccount) {
    if (!window.confirm(`¿Desvincular ${account.name}?`)) return;
    try {
      await deleteAccount(account.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar");
    }
  }

  const isYoutube = form.platform === "youtube";

  return (
    <Box component="section" sx={{ py: { xs: 5, md: 7 } }}>
      <Container maxWidth="lg">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" } }}
        >
          <Box>
            <Typography variant="overline">Sección 04 — dónde publicas</Typography>
            <Typography variant="h4" sx={{ mt: 0.5 }}>
              Cuentas vinculadas
            </Typography>
          </Box>
          <Button variant="contained" onClick={startAdd} disabled={busy} sx={{ alignSelf: { md: "flex-end" } }}>
            Vincular cuenta
          </Button>
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5, maxWidth: "62ch" }}>
          Registra los canales o perfiles donde subes tus clips. Para YouTube puedes registrar las
          credenciales OAuth de tu app de Google Cloud y conectar la cuenta para publicar clips
          directamente con la API.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        {accounts.length === 0 ? (
          <Paper sx={{ mt: 4, p: 5, textAlign: "center", borderStyle: "dashed" }}>
            <Typography variant="h6">No tienes cuentas vinculadas</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 2 }}>
              Añade tu canal de YouTube, tu TikTok o tu página de Facebook para asociar cada
              publicación a una cuenta.
            </Typography>
            <Button variant="contained" onClick={startAdd}>
              Vincular la primera cuenta
            </Button>
          </Paper>
        ) : (
          <Grid container spacing={3} sx={{ mt: 1 }}>
            {accounts.map((account) => {
              const apiReady = Boolean(account.client_id && account.has_client_secret);
              const connected = Boolean(account.token);
              return (
                <Grid size={{ xs: 12, sm: 6, md: 4 }} key={account.id}>
                  <Paper
                    sx={{
                      p: 3,
                      height: "100%",
                      display: "flex",
                      flexDirection: "column",
                      gap: 1,
                      position: "relative",
                    }}
                  >
                    {account.platform === "youtube" && (
                      <Box
                        sx={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          right: 0,
                          height: 3,
                          background: apiReady ? EDGE : "divider",
                        }}
                      />
                    )}
                    <Chip
                      size="small"
                      label={ACCOUNT_PLATFORM_LABELS[account.platform] ?? account.platform}
                      variant="outlined"
                      sx={{ alignSelf: "flex-start" }}
                    />
                    <Typography variant="h6">{account.name}</Typography>
                    {account.handle && (
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.72rem" }}
                      >
                        {account.handle}
                      </Typography>
                    )}
                    <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", mt: 0.5 }}>
                      {account.platform === "youtube" && (
                        <Chip
                          size="small"
                          label={apiReady ? "API configurada" : "sin credenciales OAuth"}
                          variant={apiReady ? "filled" : "outlined"}
                          sx={{
                            bgcolor: apiReady ? MARK : "transparent",
                            color: apiReady ? "#14161A" : undefined,
                            borderColor: apiReady ? MARK : undefined,
                            fontSize: "0.6rem",
                          }}
                        />
                      )}
                      <Chip
                        size="small"
                        label={connected ? "conectada" : "sin conectar"}
                        variant={connected ? "filled" : "outlined"}
                        sx={{
                          bgcolor: connected ? EDGE : "transparent",
                          color: connected ? "#fff" : undefined,
                          borderColor: connected ? EDGE : undefined,
                          fontSize: "0.6rem",
                        }}
                      />
                    </Stack>
                    {account.platform === "youtube" && (
                      <Button
                        size="small"
                        variant={connected ? "outlined" : "contained"}
                        color={connected ? "inherit" : "primary"}
                        onClick={() => void connectYoutube(account)}
                        disabled={connectBusy === account.id}
                        sx={{ alignSelf: "flex-start" }}
                      >
                        {connectBusy === account.id
                          ? "Conectando…"
                          : connected
                            ? "Reconectar YouTube"
                            : "Conectar YouTube"}
                      </Button>
                    )}
                    <Stack direction="row" spacing={1} sx={{ mt: "auto", pt: 1 }}>
                      <Button size="small" onClick={() => startEdit(account)}>
                        editar
                      </Button>
                      <Button size="small" color="error" onClick={() => void onDelete(account)}>
                        desvincular
                      </Button>
                    </Stack>
                  </Paper>
                </Grid>
              );
            })}
          </Grid>
        )}

        <Dialog open={showForm} onClose={() => setShowForm(false)} fullWidth maxWidth="sm">
          <DialogTitle>{editing ? "Editar cuenta" : "Vincular cuenta"}</DialogTitle>
          <Box component="form" onSubmit={onSubmit}>
            <DialogContent>
              <Box
                sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}
              >
                <TextField
                  select
                  label="Plataforma"
                  value={form.platform}
                  onChange={(e) => setForm({ ...form, platform: e.target.value })}
                >
                  {Object.entries(ACCOUNT_PLATFORM_LABELS).map(([value, label]) => (
                    <MenuItem key={value} value={value}>
                      {label}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Nombre de la cuenta"
                  placeholder="Mi canal"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
                <TextField
                  label="Handle / ID de canal"
                  placeholder="@micanal"
                  value={form.handle}
                  onChange={(e) => setForm({ ...form, handle: e.target.value })}
                />
                <TextField
                  label="Token de acceso (opcional)"
                  placeholder="Pega el refresh token si ya tienes uno"
                  value={form.token ?? ""}
                  onChange={(e) => setForm({ ...form, token: e.target.value })}
                />
              </Box>

              {isYoutube ? (
                <Collapse in={isYoutube} sx={{ mt: 3 }}>
                  <Paper variant="outlined" sx={{ p: 2, bgcolor: "#F7F9FB" }}>
                    <Typography variant="overline" sx={{ display: "block", color: EDGE }}>
                      Credenciales OAuth de Google Cloud
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
                      Son las de tu proyecto en{" "}
                      <b>Google Cloud → APIs y servicios → Credenciales → IDs de cliente de OAuth 2.0</b>{" "}
                      (tipo “Web”). Sin ellas no se pueden subir clips de forma automática; sí puedes
                      usar el respaldo con enlace a Studio.
                    </Typography>
                    <Box
                      sx={{
                        display: "grid",
                        gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
                        gap: 2,
                      }}
                    >
                      <TextField
                        label="Client ID"
                        placeholder="xxxx.apps.googleusercontent.com"
                        value={form.client_id ?? ""}
                        onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                        slotProps={{ htmlInput: { spellCheck: false } }}
                      />
                      <TextField
                        label="Client Secret"
                        type="password"
                        placeholder={
                          editing?.has_client_secret ? "••••••  (guardado)" : "GOCSPX-…"
                        }
                        value={form.client_secret}
                        onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                        slotProps={{ htmlInput: { spellCheck: false, autoComplete: "new-password" } }}
                        helperText={
                          editing?.has_client_secret && !form.client_secret
                            ? "Déjalo vacío para conservar el guardado."
                            : undefined
                        }
                      />
                    </Box>
                    <TextField
                      label="Redirect URI (autorizado en Google Cloud)"
                      placeholder="http://localhost:8000/api/youtube/callback"
                      value={form.redirect_uri ?? ""}
                      onChange={(e) => setForm({ ...form, redirect_uri: e.target.value })}
                      fullWidth
                      sx={{ mt: 2 }}
                      helperText="Debe coincidir con el URI de redireccionamiento autorizado de tu cliente OAuth en Google Cloud."
                    />
                    <Alert severity="info" sx={{ mt: 2 }}>
                      Después de guardar, pulsa <b>Conectar YouTube</b> en la tarjeta para autorizar la
                      cuenta y obtener el refresh token.
                    </Alert>
                  </Paper>
                </Collapse>
              ) : (
                <Alert severity="info" sx={{ mt: 3 }}>
                  Por ahora <b>{ACCOUNT_PLATFORM_LABELS[form.platform] ?? form.platform}</b> se
                  publica con respaldo: edgetape exporta el clip y te deja el enlace directo de
                  subida con la cuenta atribuida. La publicación automática por API real (OAuth) está{" "}
                  <b>pendiente</b> para TikTok y Facebook.
                </Alert>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setShowForm(false)} disabled={busy}>
                Cancelar
              </Button>
              <Button variant="contained" type="submit" disabled={busy}>
                {editing ? "Guardar cambios" : "Vincular cuenta"}
              </Button>
            </DialogActions>
          </Box>
        </Dialog>
      </Container>
    </Box>
  );
}
