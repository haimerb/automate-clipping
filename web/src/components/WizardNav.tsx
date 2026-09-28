import { Box, Typography } from "@mui/material";
import { INK, MARK, MONO } from "../theme";

type Step = "ingest" | "clips" | "review" | "publish" | "accounts" | "analytics";

interface StepConfig {
  key: Step;
  label: string;
  caption: string;
  icon: React.ReactNode;
}

const STEPS: StepConfig[] = [
  { key: "ingest", label: "1. INGRESAR", caption: "Sube o pega un video", icon: "📥" },
  { key: "clips", label: "2. CLIPS", caption: "Detecta momentos clave", icon: "🎬" },
  { key: "review", label: "3. REVISAR", caption: "Edita metadata y thumbnails", icon: "✏️" },
  { key: "publish", label: "4. PUBLICAR", caption: "Configura destinos y publica", icon: "🚀" },
  { key: "accounts", label: "5. CUENTAS", caption: "Canales vinculados", icon: "🔗" },
  { key: "analytics", label: "6. GANANCIAS", caption: "Mide tu rendimiento", icon: "📊" },
];

interface Props {
  currentStep: Step;
  completedSteps: Step[];
  onStepClick?: (step: Step) => void;
}

export default function WizardNav({ currentStep, completedSteps, onStepClick }: Props) {
  const stepOrder = STEPS.map((s) => s.key);
  const currentIndex = stepOrder.indexOf(currentStep);

  return (
    <Box
      component="nav"
      aria-label="Pasos del asistente de publicación"
      sx={{
        display: "flex",
        justifyContent: "space-between",
        position: "relative",
        px: { xs: 0.5, md: 2 },
        mb: 4,
        "&::before": {
          content: '""',
          position: "absolute",
          top: "50%",
          left: 0,
          right: 0,
          height: 3,
          background: "linear-gradient(90deg, var(--mui-palette-divider) 50%, var(--mui-palette-primary-main) 50%)",
          backgroundSize: `${100 / (STEPS.length - 1)}% 100%`,
          transform: "translateY(-50%)",
          zIndex: 0,
        },
      }}
    >
      {STEPS.map((step) => {
        const isCompleted = completedSteps.includes(step.key);
        const isCurrent = step.key === currentStep;
        const stepIndex = stepOrder.indexOf(step.key);
        const isFuture = stepIndex > currentIndex;
        const canActivate = Boolean(onStepClick) && (isCompleted || isCurrent);

        return (
          <Box
            key={step.key}
            role={onStepClick ? "button" : undefined}
            tabIndex={canActivate ? 0 : -1}
            aria-current={isCurrent ? "step" : undefined}
            aria-disabled={!canActivate}
            aria-label={`${step.label} — ${step.caption}${canActivate ? "" : ", no disponible"}`}
            onKeyDown={(e) => {
              if (onStepClick && (e.key === "Enter" || e.key === " ") && canActivate) {
                e.preventDefault();
                onStepClick(step.key);
              }
            }}
            onClick={() => onStepClick?.(step.key)}
            sx={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 1,
              position: "relative",
              zIndex: 1,
              flex: 1,
              minWidth: 0,
              cursor: canActivate ? "pointer" : "default",
              opacity: isFuture && !onStepClick ? 0.5 : 1,
              transition: "opacity .2s ease",
              "&:focus-visible": { outline: `2px solid ${MARK}`, outlineOffset: 2, borderRadius: 2 },
            }}
          >
            <Box
              aria-hidden
              sx={{
                width: 44,
                height: 44,
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "1.2rem",
                background: isCompleted || isCurrent
                  ? "linear-gradient(135deg, var(--mui-palette-primary-main) 0%, #3B6AD1 100%)"
                  : "var(--mui-palette-divider)",
                color: isCompleted || isCurrent ? MARK : "text.secondary",
                border: isCurrent ? `3px solid ${MARK}` : "none",
                boxShadow: isCurrent
                  ? "0 0 0 4px rgba(255,198,71,0.3), 0 4px 12px rgba(30,58,138,0.3)"
                  : isCompleted
                  ? "0 0 0 2px rgba(255,198,71,0.2)"
                  : "none",
                transition: "all .3s ease",
                position: "relative",
                "&::after": isCompleted
                  ? {
                      content: '""',
                      position: "absolute",
                      bottom: -8,
                      left: "50%",
                      transform: "translateX(-50%)",
                      width: 0,
                      height: 0,
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderTop: "8px solid var(--mui-palette-primary-main)",
                    }
                  : undefined,
              }}
            >
              {isCompleted ? "✓" : step.icon}
            </Box>
            <Typography
              variant="caption"
              sx={{
                fontFamily: MONO,
                fontSize: { xs: "0.5rem", md: "0.6rem" },
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: isCompleted || isCurrent ? INK : "text.secondary",
                textAlign: "center",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: "100%",
              }}
            >
              {step.label}
            </Typography>
            <Typography
              variant="caption"
              sx={{
                fontSize: "0.58rem",
                color: "text.secondary",
                textAlign: "center",
                whiteSpace: "nowrap",
                maxWidth: 100,
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {step.caption}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}