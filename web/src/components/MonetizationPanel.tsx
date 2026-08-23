import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  List,
  ListItem,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  PLATFORM_LABELS,
  POST_STATUS_LABELS,
  createPost,
  deletePost,
  getAccounts,
  getPosts,
  updatePost,
  formatMoney,
} from "../api";
import type { Clip, LinkedAccount, PlatformPost } from "../api";
import { MONO } from "../theme";
import ConfirmDialog from "./ConfirmDialog";

interface Props {
  jobId: string;
  clip: Clip;
  refreshToken?: number;
}

interface FormState {
  platform: string;
  status: "no_publicado" | "listo" | "publicado";
  url: string;
  views: string;
  likes: string;
  comments: string;
  earnings: string;
  currency: string;
  account: string;
}

const EMPTY_FORM: FormState = {
  platform: "youtube_shorts",
  status: "no_publicado",
  url: "",
  views: "",
  likes: "",
  comments: "",
  earnings: "",
  currency: "USD",
  account: "",
};

function toForm(post: PlatformPost): FormState {
  return {
    platform: post.platform,
    status: post.status as FormState["status"],
    url: post.url ?? "",
    views: String(post.views),
    likes: String(post.likes),
    comments: String(post.comments),
    earnings: String(post.earnings),
    currency: post.currency,
    account: post.account ?? "",
  };
}

function toInput(f: FormState) {
  return {
    platform: f.platform,
    status: f.status,
    url: f.url.trim() || null,
    views: Number(f.views) || 0,
    likes: Number(f.likes) || 0,
    comments: Number(f.comments) || 0,
    earnings: Number(f.earnings) || 0,
    currency: f.currency.trim() || "USD",
    account: f.account.trim() || null,
  };
}

export default function MonetizationPanel({ jobId, clip, refreshToken = 0 }: Props) {
  const [posts, setPosts] = useState<PlatformPost[]>([]);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<PlatformPost | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<PlatformPost | null>(null);

  async function refresh() {
    const all = await getPosts(jobId);
    setPosts(all.filter((p) => p.clip_id === clip.id));
  }

  useEffect(() => {
    refresh().catch(() => setPosts([]));
    getAccounts().then(setAccounts).catch(() => setAccounts([]));
  }, [jobId, clip.id, refreshToken]);

  function startAdd() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function startEdit(post: PlatformPost) {
    setEditing(post);
    setForm(toForm(post));
    setShowForm(true);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await updatePost(jobId, editing.id, toInput(form));
      } else {
        await createPost(jobId, clip.id, toInput(form));
      }
      setShowForm(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(post: PlatformPost) {
    setDeleteConfirm(post);
  }

  async function confirmDelete() {
    if (!deleteConfirm) return;
    try {
      await deletePost(jobId, deleteConfirm.id);
      setDeleteConfirm(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar");
      setDeleteConfirm(null);
    }
  }

  const clipEarnings = posts.reduce((acc, p) => acc + p.earnings, 0);
  const clipViews = posts.reduce((acc, p) => acc + p.views, 0);

  return (
    <Box component="section" sx={{ mt: 5 }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" } }}
      >
        <Box>
          <Typography variant="overline">Panel del clip — publicación y ganancias</Typography>
          <Typography variant="h5" sx={{ mt: 0.5 }}>
            Monetiza {clip.id.toUpperCase()}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Typography variant="body2" color="text.secondary">
            <b>{clipViews.toLocaleString("es")}</b> vistas
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <b>{formatMoney(clipEarnings, "USD")}</b> ganados
          </Typography>
          <Button variant="contained" onClick={startAdd} disabled={busy}>
            Registrar publicación
          </Button>
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      {posts.length === 0 && !showForm ? (
        <Paper sx={{ mt: 2, p: 3, borderStyle: "dashed" }}>
          <Typography variant="body2" color="text.secondary">
            Aún no has registrado publicaciones para este clip. Sube el clip exportado a Shorts,
            TikTok o Reels y lleva la cuenta de vistas y ganancias aquí.
          </Typography>
        </Paper>
      ) : (
        <Paper sx={{ mt: 2 }}>
          <List disablePadding>
            {posts.map((post, i) => (
              <Box key={post.id}>
                {i > 0 && <Divider component="li" />}
                <ListItem
                  sx={{
                    flexWrap: "wrap",
                    gap: 1.5,
                    justifyContent: "space-between",
                  }}
                >
                  <Stack spacing={0.5}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                      <Typography variant="subtitle2">
                        {PLATFORM_LABELS[post.platform] ?? post.platform}
                      </Typography>
                      <Chip
                        size="small"
                        label={POST_STATUS_LABELS[post.status] ?? post.status}
                        color={post.status === "publicado" ? "primary" : "default"}
                        variant={post.status === "publicado" ? "filled" : "outlined"}
                      />
                    </Stack>
                    {post.account && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ fontFamily: MONO, fontSize: "0.62rem" }}
                      >
                        {post.account}
                      </Typography>
                    )}
                  </Stack>
                  <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                    <Typography variant="body2" color="text.secondary">
                      {post.views.toLocaleString("es")} vistas
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {post.likes.toLocaleString("es")} me gusta
                    </Typography>
                    <Typography variant="subtitle2">
                      {formatMoney(post.earnings, post.currency)}
                    </Typography>
                    <Stack direction="row" spacing={0.5}>
                      {post.url && (
                        <Button size="small" href={post.url} target="_blank" rel="noreferrer">
                          ver ↗
                        </Button>
                      )}
                      <Button size="small" onClick={() => startEdit(post)}>
                        editar
                      </Button>
                      <Button size="small" color="error" onClick={() => void onDelete(post)}>
                        borrar
                      </Button>
                    </Stack>
                  </Stack>
                </ListItem>
              </Box>
            ))}
          </List>
        </Paper>
      )}

      {showForm && (
        <Paper component="form" onSubmit={onSubmit} sx={{ mt: 2, p: 3 }}>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
              gap: 2,
            }}
          >
            <TextField
              select
              label="Plataforma"
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
            >
              {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                <MenuItem key={value} value={value}>
                  {label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Estado"
              value={form.status}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as FormState["status"] })
              }
            >
              <MenuItem value="no_publicado">Sin publicar</MenuItem>
              <MenuItem value="listo">Listo para subir</MenuItem>
              <MenuItem value="publicado">Publicado</MenuItem>
            </TextField>
            <TextField
              select
              label="Cuenta vinculada"
              value={form.account}
              onChange={(e) => setForm({ ...form, account: e.target.value })}
            >
              <MenuItem value="">— sin cuenta —</MenuItem>
              {accounts.map((acc) => (
                <MenuItem key={acc.id} value={acc.name}>
                  {acc.name}
                  {acc.handle ? ` (${acc.handle})` : ""}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="URL de la publicación"
              placeholder="https://…"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
            />
            <TextField
              label="Vistas"
              type="number"
              slotProps={{ htmlInput: { min: 0 } }}
              value={form.views}
              onChange={(e) => setForm({ ...form, views: e.target.value })}
            />
            <TextField
              label="Me gusta"
              type="number"
              slotProps={{ htmlInput: { min: 0 } }}
              value={form.likes}
              onChange={(e) => setForm({ ...form, likes: e.target.value })}
            />
            <TextField
              label="Comentarios"
              type="number"
              slotProps={{ htmlInput: { min: 0 } }}
              value={form.comments}
              onChange={(e) => setForm({ ...form, comments: e.target.value })}
            />
            <TextField
              label="Ganancias"
              type="number"
              slotProps={{ htmlInput: { min: 0, step: "0.01" } }}
              value={form.earnings}
              onChange={(e) => setForm({ ...form, earnings: e.target.value })}
            />
            <TextField
              label="Moneda"
              slotProps={{ htmlInput: { maxLength: 3 } }}
              value={form.currency}
              onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            />
          </Box>
          <Stack direction="row" spacing={1.5} sx={{ mt: 2.5 }}>
            <Button variant="contained" type="submit" disabled={busy}>
              {editing ? "Guardar cambios" : "Añadir publicación"}
            </Button>
            <Button onClick={() => setShowForm(false)} disabled={busy}>
              Cancelar
            </Button>
          </Stack>
        </Paper>
      )}
      <ConfirmDialog
        open={deleteConfirm !== null}
        title="Eliminar publicación"
        message="¿Eliminar este registro de publicación? Esta acción no se puede deshacer."
        confirmLabel="Eliminar"
        cancelLabel="Cancelar"
        severity="error"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteConfirm(null)}
      />
    </Box>
  );
}
