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
  Skeleton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  ACCOUNT_PLATFORM_LABELS,
  createAccount,
  deleteAccount,
  getAccounts,
  getMetaAuthUrl,
  getTiktokAuthUrl,
  getYoutubeAuthUrl,
  updateAccount,
} from "../api";
import type { AccountInput, LinkedAccount } from "../api";
import { EDGE, MARK, MONO, ON_ACCENT, SURFACE } from "../theme";
import ConfirmDialog from "./ConfirmDialog";
import Branding from "./Branding";
import { useToast } from "./ToastContext";

const EMPTY: AccountInput = {
  platform: "youtube",
  name: "",
  handle: "",
  token: "",
  client_id: "",
  client_secret: "",
  redirect_uri: "",
};

/** Plataformas con OAuth propio (el resto sigue con el respaldo manual). */
const OAUTH_PLATFORMS: Record<string, "youtube" | "tiktok" | "meta"> = {
  youtube: "youtube",
  tiktok: "tiktok",
  facebook: "meta",
  instagram: "meta",
};

const OAUTH_HELP: Record<"youtube" | "tiktok" | "meta", { title: string; body: React.ReactNode }> = {
  youtube: {
    title: "Credenciales OAuth de Google Cloud",
    body: (
      <>
        Son las de tu proyecto en{" "}
        <b>Google Cloud → APIs y servicios → Credenciales → IDs de cliente de OAuth 2.0</b>{" "}
        (tipo “Web”). Sin ellas no se pueden subir clips de forma automática; sí puedes
        usar el respaldo con enlace a Studio.
      </>
    ),
  },
  tiktok: {
    title: "Credenciales de TikTok for Developers",
    body: (
      <>
        De tu app en <b>developers.tiktok.com → My Apps → Content Posting API</b>. Pega el{" "}
        <b>Client Key</b> y el <b>Client Secret</b>. Mientras la app no esté auditada, TikTok
        solo acepta publicaciones <b>privadas (SELF_ONLY)</b>: el clip se sube pero queda en
        tu perfil como privado hasta que aprueben la app.
      </>
    ),
  },
  meta: {
    title: "Credenciales de Meta (Facebook Login)",
    body: (
      <>
        De tu app en <b>developers.facebook.com → Facebook Login → Settings</b>. Pega el{" "}
        <b>Client ID</b> y el <b>Client Secret</b>, y activa los permisos{" "}
        <code>pages_show_list</code>, <code>pages_manage_posts</code> e{" "}
        <code>instagram_basic, instagram_content_publish</code>. Al conectar se detectan tus
        páginas y la cuenta de Instagram business asociada.
      </>
    ),
  },
};

const REDIRECT_HINT: Record<"youtube" | "tiktok" | "meta", string> = {
  youtube: "http://localhost:8000/api/youtube/callback",
  tiktok: "http://localhost:8000/api/tiktok/callback",
  meta: "http://localhost:8000/api/meta/callback",
};

interface FormState extends AccountInput {
  client_secret: string;
  redirect_uri: string;
}

export default function Accounts() {
  const toast = useToast();
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<LinkedAccount | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY as FormState);
  const [busy, setBusy] = useState(false);
  const [connectBusy, setConnectBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<LinkedAccount | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setAccounts(await getAccounts());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar las cuentas");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const search = window.location.search;
    const clean = () => window.history.replaceState({}, "", window.location.pathname);
    const done: Record<string, string> = {
      "youtube=connected": "YouTube conectado. Ya puedes publicar clips desde Edgetape.",
      "tiktok=connected": "TikTok conectado. Edgetape ya puede subir tus clips.",
      "meta=connected": "Cuenta de Meta conectada (página e Instagram business detectados).",
    };
    const failed: Record<string, string> = {
      "youtube=error": "No se pudo conectar YouTube. Revisa las credenciales y el token en la terminal del servidor.",
      "tiktok=error": "No se pudo conectar TikTok. Revisa que el Client Key/Secret sean de la app correcta y que el redirect URI esté autorizado.",
      "meta=error": "No se pudo conectar Meta. Revisa el Client ID/Secret y los permisos de la app.",
      "meta=empty": "El login de Meta no devolvió ninguna página administrada.",
      "meta=no_instagram": "Ninguna de tus páginas tiene una cuenta de Instagram business vinculada.",
    };
    const key = Object.keys(done).find((k) => search.includes(k));
    if (key) {
      void refresh();
      clean();
      setSuccessMsg(done[key]);
      return;
    }
    const bad = Object.keys(failed).find((k) => search.includes(k));
    if (bad) {
      clean();
      setError(failed[bad]);
    }
  }, []);

  async function connect(account: LinkedAccount) {
    const kind = OAUTH_PLATFORMS[account.platform];
    if (!kind) return;
    setConnectBusy(account.id);
    setError(null);
    try {
      const { auth_url } =
        kind === "youtube"
          ? await getYoutubeAuthUrl(account.id)
          : kind === "tiktok"
            ? await getTiktokAuthUrl(account.id)
            : await getMetaAuthUrl(account.id);
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
      toast.success(editing ? "Cambios guardados" : "Cuenta vinculada");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
      toast.error(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(account: LinkedAccount) {
    setDeleteConfirm(account);
  }

  async function confirmDelete() {
    if (!deleteConfirm) return;
    try {
      await deleteAccount(deleteConfirm.id);
      setDeleteConfirm(null);
      await refresh();
      toast.success("Cuenta desvinculada");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar");
      setDeleteConfirm(null);
    }
  }

  const oauthKind = OAUTH_PLATFORMS[form.platform] ?? null;

  return (
    <Box component="section" sx={{ py: { xs: 5, md: 7 } }}>
      <Container maxWidth="lg">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" } }}
        >
          <Box>
            <Typography variant="overline">Dónde publicas</Typography>
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

        {accounts.length > 0 && (
          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap" }}>
            <Chip
              size="small"
              variant="outlined"
              label={`${accounts.length} ${accounts.length === 1 ? "cuenta" : "cuentas"}`}
            />
            <Chip
              size="small"
              variant="filled"
              sx={{ bgcolor: MARK, color: ON_ACCENT }}
              label={`${accounts.filter((a) => a.token).length} conectadas`}
            />
          </Stack>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Grid container spacing={3} sx={{ mt: 1 }}>
            {[0, 1, 2].map((i) => (
              <Grid size={{ xs: 12, sm: 6, md: 4 }} key={i}>
                <Paper sx={{ p: 3, height: "100%" }}>
                  <Skeleton width={90} height={22} />
                  <Skeleton width="60%" height={30} sx={{ mt: 1 }} />
                  <Skeleton width="40%" height={16} sx={{ mt: 1 }} />
                  <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                    <Skeleton width={110} height={24} />
                    <Skeleton width={110} height={24} />
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        ) : accounts.length === 0 ? (
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
                    {account.platform !== "youtube" && (
                      <Box
                        sx={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          right: 0,
                          height: 3,
                          background: connected ? EDGE : "divider",
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
                        sx={{ fontFamily: MONO, fontSize: "0.72rem" }}
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
                            color: apiReady ? ON_ACCENT : undefined,
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
                        onClick={() => void connect(account)}
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
                    {account.platform === "tiktok" && (
                      <Button
                        size="small"
                        variant={connected ? "outlined" : "contained"}
                        color={connected ? "inherit" : "primary"}
                        onClick={() => void connect(account)}
                        disabled={connectBusy === account.id}
                        sx={{ alignSelf: "flex-start" }}
                      >
                        {connectBusy === account.id
                          ? "Conectando…"
                          : connected
                            ? "Reconectar TikTok"
                            : "Conectar TikTok"}
                      </Button>
                    )}
                    {(account.platform === "facebook" || account.platform === "instagram") && (
                      <Button
                        size="small"
                        variant={connected ? "outlined" : "contained"}
                        color={connected ? "inherit" : "primary"}
                        onClick={() => void connect(account)}
                        disabled={connectBusy === account.id}
                        sx={{ alignSelf: "flex-start" }}
                      >
                        {connectBusy === account.id
                          ? "Conectando…"
                          : connected
                            ? "Reconectar con Meta"
                            : "Conectar con Meta"}
                      </Button>
                    )}
                    {account.platform === "instagram" && !account.token && (
                      <Typography variant="caption" color="text.secondary">
                        Instagram necesita <code>EDGETAPE_PUBLIC_BASE_URL</code> en el servidor para
                        que Meta pueda descargar el video; sin eso la publicación queda manual.
                      </Typography>
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

              {oauthKind ? (
                <Collapse in={Boolean(oauthKind)} sx={{ mt: 3 }}>
                  <Paper variant="outlined" sx={{ p: 2, bgcolor: SURFACE }}>
                    <Typography variant="overline" sx={{ display: "block", color: EDGE }}>
                      {OAUTH_HELP[oauthKind].title}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
                      {OAUTH_HELP[oauthKind].body}
                    </Typography>
                    <Box
                      sx={{
                        display: "grid",
                        gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
                        gap: 2,
                      }}
                    >
                      <TextField
                        label={oauthKind === "tiktok" ? "Client Key" : "Client ID"}
                        placeholder={
                          oauthKind === "tiktok"
                            ? "aw1234567890"
                            : oauthKind === "meta"
                              ? "1234567890123456"
                              : "xxxx.apps.googleusercontent.com"
                        }
                        value={form.client_id ?? ""}
                        onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                        slotProps={{ htmlInput: { spellCheck: false } }}
                      />
                      <TextField
                        label="Client Secret"
                        type="password"
                        placeholder={
                          editing?.has_client_secret
                            ? "••••••  (guardado)"
                            : oauthKind === "meta"
                              ? "abc123…"
                              : "GOCSPX-…"
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
                      label="Redirect URI (autorizado en la app)"
                      placeholder={REDIRECT_HINT[oauthKind]}
                      value={form.redirect_uri ?? ""}
                      onChange={(e) => setForm({ ...form, redirect_uri: e.target.value })}
                      fullWidth
                      sx={{ mt: 2 }}
                      helperText="Debe coincidir con la URL de redireccionamiento autorizada en la app. En producción pon el dominio real (no localhost)."
                    />
                    <Alert severity="info" sx={{ mt: 2 }}>
                      Después de guardar, pulsa{" "}
                      <b>
                        {form.platform === "youtube"
                          ? "Conectar YouTube"
                          : form.platform === "tiktok"
                            ? "Conectar TikTok"
                            : "Conectar con Meta"}
                      </b>{" "}
                      en la tarjeta para autorizar la cuenta y obtener el token.
                    </Alert>
                  </Paper>
                </Collapse>
              ) : (
                <Alert severity="info" sx={{ mt: 3 }}>
                  <b>{ACCOUNT_PLATFORM_LABELS[form.platform] ?? form.platform}</b> se publica con
                  respaldo: Edgetape exporta el clip y te deja el enlace directo de subida con la
                  cuenta atribuida.
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
        {successMsg && (
          <Alert severity="success" sx={{ mt: 3 }} onClose={() => setSuccessMsg(null)}>
            {successMsg}
          </Alert>
        )}
        <ConfirmDialog
          open={deleteConfirm !== null}
          title="Desvincular cuenta"
          message={`¿Desvincular ${deleteConfirm?.name ?? ""}? Esta acción no se puede deshacer.`}
          confirmLabel="Desvincular"
          cancelLabel="Cancelar"
          severity="error"
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleteConfirm(null)}
        />

        <Branding />
      </Container>
    </Box>
  );
}
