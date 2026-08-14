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

  return (
    <Box component="section" sx={{ py: { xs: 5, md: 7 } }}>
      <Container maxWidth="lg">
        <Typography variant="overline">Sección 05 — panel de ganancias</Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          Lo que estás ganando
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          Registra manualmente cada publicación que haces de tus clips. Así tienes el total por
          plataforma y por video sin ir plataforma por plataforma.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {error}
          </Alert>
        )}

        <Grid container spacing={2.5} sx={{ mt: 1 }}>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <Paper sx={{ p: 3, bgcolor: "#FFC647" }}>
              <Typography variant="overline" sx={{ color: "#14161A" }}>
                Ganancia total
              </Typography>
              <Typography variant="h4" sx={{ color: "#14161A", mt: 0.5 }}>
                {formatMoney(totalByPlatform, "USD")}
              </Typography>
              <Typography variant="body2" sx={{ color: "#14161A", opacity: 0.7 }}>
                suma de todas las publicaciones
              </Typography>
            </Paper>
          </Grid>
          <Grid size={{ xs: 6, sm: 4, md: 2 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Videos procesados</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {stats?.jobs ?? 0}
              </Typography>
            </Paper>
          </Grid>
          <Grid size={{ xs: 6, sm: 4, md: 2 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Clips generados</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {stats?.clips ?? 0}
              </Typography>
            </Paper>
          </Grid>
          <Grid size={{ xs: 6, sm: 4, md: 2 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Publicaciones</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {stats?.posts ?? 0}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {stats?.publicados ?? 0} publicadas · {stats ? stats.posts - stats.publicados : 0}{" "}
                pendientes
              </Typography>
            </Paper>
          </Grid>
          <Grid size={{ xs: 6, sm: 4, md: 2 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Vistas totales</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {(stats?.total_views ?? 0).toLocaleString("es")}
              </Typography>
            </Paper>
          </Grid>
        </Grid>

        <Grid container spacing={2.5} sx={{ mt: 0.5 }}>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Me gusta</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {(stats?.total_likes ?? 0).toLocaleString("es")}
              </Typography>
            </Paper>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <Paper sx={{ p: 3, height: "100%" }}>
              <Typography variant="overline">Cuentas vinculadas</Typography>
              <Typography variant="h4" sx={{ mt: 0.5 }}>
                {accounts.length}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {accounts.length === 0
                  ? "vincula tus cuentas en CUENTAS"
                  : accounts.map((a) => ACCOUNT_PLATFORM_LABELS[a.platform] ?? a.platform).join(" · ")}
              </Typography>
            </Paper>
          </Grid>
        </Grid>

        <Grid container spacing={4} sx={{ mt: 2 }}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Typography variant="h5" sx={{ mb: 2 }}>
              Por plataforma
            </Typography>
            {platforms.length === 0 ? (
              <Paper sx={{ p: 3, borderStyle: "dashed" }}>
                <Typography variant="body2" color="text.secondary">
                  Todavía no hay publicaciones registradas.
                </Typography>
              </Paper>
            ) : (
              <Paper sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Plataforma</TableCell>
                      <TableCell align="right">Posts</TableCell>
                      <TableCell align="right">Vistas</TableCell>
                      <TableCell align="right">Ganancias</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {platforms.map(([key, tot]) => (
                      <TableRow key={key}>
                        <TableCell>{PLATFORM_LABELS[key] ?? key}</TableCell>
                        <TableCell align="right">{tot.posts}</TableCell>
                        <TableCell align="right">{tot.views.toLocaleString("es")}</TableCell>
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
            <Typography variant="h5" sx={{ mb: 2 }}>
              Últimas publicaciones
            </Typography>
            {!stats || stats.recent_posts.length === 0 ? (
              <Paper sx={{ p: 3, borderStyle: "dashed" }}>
                <Typography variant="body2" color="text.secondary">
                  Cuando registres publicaciones aparecerán aquí.
                </Typography>
              </Paper>
            ) : (
              <Stack spacing={2}>
                {stats.recent_posts.map((post) => (
                  <Paper key={post.post_id} sx={{ p: 2.5 }}>
                    <Stack
                      direction={{ xs: "column", md: "row" }}
                      spacing={1.5}
                      sx={{ justifyContent: "space-between", alignItems: { xs: "stretch", md: "center" } }}
                    >
                      <Box>
                        <Typography variant="subtitle2">{post.title}</Typography>
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 0.5 }}>
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
                        <Typography variant="body2" color="text.secondary">
                          {post.views.toLocaleString("es")} vistas
                        </Typography>
                        <Typography variant="subtitle2">
                          {formatMoney(post.earnings, post.currency)}
                        </Typography>
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

        <Box sx={{ mt: 5, textAlign: "center" }}>
          <Button variant="contained" onClick={onNewJob}>
            Procesar un video nuevo
          </Button>
        </Box>
      </Container>
    </Box>
  );
}
