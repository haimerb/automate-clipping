import { useEffect, useState } from "react";
import {
  ACCOUNT_PLATFORM_LABELS,
  PLATFORM_LABELS,
  formatMoney,
  getAccounts,
  getDashboard,
  getJob,
} from "../api";
import type { DashboardStats, Job, LinkedAccount } from "../api";
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { EDGE, MARK } from "../theme";

interface Props {
  onNewJob: () => void;
  onOpenJob: (job: Job) => void;
}

async function openJob(jobId: string, onOpenJob: (job: Job) => void) {
  const job = await getJob(jobId);
  if (job.status !== "done") {
    window.alert("Este video aún no está listo para ver clips.");
    return;
  }
  onOpenJob(job);
}

function StatCard({
  label,
  value,
  caption,
  highlight = false,
}: {
  label: string;
  value: React.ReactNode;
  caption?: string;
  highlight?: boolean;
}) {
  return (
    <Paper
      sx={{
        p: 2.5,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: 0.5,
        ...(highlight ? { bgcolor: MARK } : {}),
      }}
    >
      <Typography
        variant="overline"
        sx={{ display: "block", fontSize: "0.58rem", ...(highlight ? { color: "#14161A" } : {}) }}
      >
        {label}
      </Typography>
      <Typography
        variant="h4"
        sx={{
          lineHeight: 1.1,
          ...(highlight ? { color: "#14161A" } : {}),
        }}
      >
        {value}
      </Typography>
      {caption && (
        <Typography
          variant="caption"
          sx={{
            mt: "auto",
            pt: 0.5,
            fontSize: "0.68rem",
            ...(highlight ? { color: "rgba(20,22,26,.72)" } : { color: "text.secondary" }),
          }}
        >
          {caption}
        </Typography>
      )}
    </Paper>
  );
}

export default function Dashboard({ onNewJob, onOpenJob }: Props) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setStats(await getDashboard());
      setAccounts(await getAccounts());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el panel");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const platforms = Object.entries(stats?.by_platform ?? {});
  const totalByPlatform = stats?.total_earnings ?? 0;
  const pending = stats ? stats.posts - stats.publicados : 0;

  return (
    <Container maxWidth="lg" sx={{ py: { xs: 4, md: 6 } }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "flex-end" }, mb: 3 }}
      >
        <Box>
          <Typography variant="overline" sx={{ display: "block" }}>
            Panel de ganancias
          </Typography>
          <Typography variant="h4" sx={{ mt: 0.5 }}>
            Tu rendimiento
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "60ch" }}>
            Registra manualmente cada publicación de tus clips y sigue el total por plataforma y por
            video.
          </Typography>
        </Box>
        <Button variant="contained" onClick={onNewJob} sx={{ alignSelf: { md: "flex-end" } }}>
          Procesar video nuevo
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, sm: 6, md: 4 }}>
          <StatCard
            label="Ganancia total"
            value={formatMoney(totalByPlatform, "USD")}
            caption="suma de todas las publicaciones"
            highlight
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 2 }}>
          <StatCard label="Videos procesados" value={stats?.jobs ?? 0} />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 2 }}>
          <StatCard label="Clips generados" value={stats?.clips ?? 0} />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 2 }}>
          <StatCard
            label="Publicaciones"
            value={stats?.posts ?? 0}
            caption={`${stats?.publicados ?? 0} publicadas · ${pending} pendientes`}
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 2 }}>
          <StatCard
            label="Vistas totales"
            value={(stats?.total_views ?? 0).toLocaleString("es")}
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 3 }}>
          <StatCard
            label="Me gusta"
            value={(stats?.total_likes ?? 0).toLocaleString("es")}
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 4, md: 3 }}>
          <StatCard
            label="Cuentas vinculadas"
            value={accounts.length}
            caption={
              accounts.length === 0
                ? "vincula tus cuentas en CUENTAS"
                : accounts.map((a) => ACCOUNT_PLATFORM_LABELS[a.platform] ?? a.platform).join(" · ")
            }
          />
        </Grid>
      </Grid>

      <Grid container spacing={4} sx={{ mt: 2 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Por plataforma
          </Typography>
          {platforms.length === 0 ? (
            <Box
              sx={{
                p: 4,
                border: "1px dashed",
                borderColor: "divider",
                borderRadius: 2,
                bgcolor: "background.paper",
                textAlign: "center",
              }}
            >
              <Typography variant="body2" color="text.secondary">
                Todavía no hay publicaciones registradas.
              </Typography>
            </Box>
          ) : (
            <Paper sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Plataforma</TableCell>
                    <TableCell align="right">Posts</TableCell>
                    <TableCell align="right">Vistas</TableCell>
                    <TableCell align="right">Me gusta</TableCell>
                    <TableCell align="right">Ganancias</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {platforms.map(([key, tot]) => (
                    <TableRow key={key}>
                      <TableCell sx={{ fontWeight: 600 }}>{PLATFORM_LABELS[key] ?? key}</TableCell>
                      <TableCell align="right">{tot.posts}</TableCell>
                      <TableCell align="right" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                        {tot.views.toLocaleString("es")}
                      </TableCell>
                      <TableCell align="right" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}>
                        {tot.likes.toLocaleString("es")}
                      </TableCell>
                      <TableCell align="right" sx={{ fontWeight: 600 }}>
                        {formatMoney(tot.earnings, "USD")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Paper>
          )}
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Últimas publicaciones
          </Typography>
          {!stats || stats.recent_posts.length === 0 ? (
            <Box
              sx={{
                p: 4,
                border: "1px dashed",
                borderColor: "divider",
                borderRadius: 2,
                bgcolor: "background.paper",
                textAlign: "center",
              }}
            >
              <Typography variant="body2" color="text.secondary">
                Cuando registres publicaciones aparecerán aquí.
              </Typography>
            </Box>
          ) : (
            <Stack spacing={2}>
              {stats.recent_posts.map((post) => (
                <Paper key={post.post_id} sx={{ p: 2 }}>
                  <Stack
                    direction={{ xs: "column", md: "row" }}
                    spacing={1.5}
                    sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "center" } }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography
                        variant="subtitle2"
                        sx={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                      >
                        {post.title}
                      </Typography>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 0.5, flexWrap: "wrap" }}>
                        <Typography variant="caption" color="text.secondary">
                          {PLATFORM_LABELS[post.platform] ?? post.platform}
                        </Typography>
                        <Chip
                          size="small"
                          label={post.status === "publicado" ? "publicado" : "sin publicar"}
                          color={post.status === "publicado" ? "primary" : "default"}
                          variant={post.status === "publicado" ? "filled" : "outlined"}
                        />
                      </Stack>
                    </Box>
                    <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.74rem" }}
                      >
                        {post.views.toLocaleString("es")} vistas
                      </Typography>
                      <Typography variant="subtitle2">{formatMoney(post.earnings, post.currency)}</Typography>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => void openJob(post.job_id, onOpenJob).catch(() => {})}
                      >
                        abrir clips
                      </Button>
                    </Stack>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </Grid>
      </Grid>

      <Box sx={{ mt: 5, display: "flex", gap: 1.5, alignItems: "center" }}>
        <Box aria-hidden sx={{ flex: 1, height: 8, borderRadius: 2, background: `repeating-linear-gradient(90deg, transparent 0 6px, ${EDGE} 6px 8px, transparent 8px 14px)`, opacity: 0.5 }} />
        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.6rem", letterSpacing: "0.1em" }}>
          EDGETAPE · RENDIMIENTO
        </Typography>
        <Box aria-hidden sx={{ flex: 1, height: 8, borderRadius: 2, background: `repeating-linear-gradient(90deg, transparent 0 6px, ${EDGE} 6px 8px, transparent 8px 14px)`, opacity: 0.5 }} />
      </Box>
    </Container>
  );
}
