import {
  CalendarDays,
  CalendarPlus,
  Check,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { format12 } from "../../lib/time";
import { useIntelligence } from "./IntelligenceProvider";
import { Avatar, EmptyState, IntelButton } from "./components";
import { ProgramRecommendationDialog } from "./ProgramRecommendationDialog";
import { shortDate } from "./model";
import type { Recommendation } from "./types";

export function RecommendationsScreen() {
  const { path, recommendations, doctors, state, mode } = useIntelligence();
  const [planning, setPlanning] = useState<Recommendation | null>(null);
  const [scheduled, setScheduled] = useState<{
    name: string;
    day: string;
  } | null>(null);
  const pending = recommendations.filter((r) => !state.decisions[r.id]);
  const next = pending[0];
  const doctor = doctors.find((d) => d.id === next?.doctorId);
  const upcoming = pending.slice(1);
  const accepted = recommendations.filter(
    (r) => state.decisions[r.id]?.status === "accepted",
  ).length;
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>Recomendaciones</h1>
        <p>Tu siguiente visita, en un vistazo.</p>
      </header>
      {scheduled && (
        <div className="intel-scheduled-notice" role="status">
          <Check size={18} />
          <span>
            <strong>Visita programada</strong>
            <small>{scheduled.name}</small>
          </span>
          <Link to={path(`calendario?fecha=${scheduled.day}`)}>Ver agenda</Link>
        </div>
      )}
      {mode === "empty" ? (
        <EmptyState
          icon={Sparkles}
          title="Aún no hay recomendaciones"
          description="Cuando tus visitas estén conectadas, aquí aparecerá el próximo paso sugerido."
        />
      ) : next && doctor ? (
        <>
          <article className="intel-next-visit" aria-labelledby="next-doctor">
            <div className="intel-next-label">
              <Sparkles size={16} /> TU PRÓXIMA VISITA
            </div>
            <div className="intel-mobile-identity">
              <Avatar doctor={doctor} />
              <div>
                <h2 id="next-doctor">{doctor.name}</h2>
                <p>{doctor.institution}</p>
              </div>
            </div>
            <div className="intel-next-slot">
              <CalendarDays size={18} />
              <span>
                <strong>{shortDate(next.day)}</strong>
                <small>Fecha sugerida</small>
              </span>
              <span>
                <strong>{format12(next.time)}</strong>
                <small>Hora de Bogotá</small>
              </span>
            </div>
            <p className="intel-next-reason">{next.shortReason}</p>
            <IntelButton onClick={() => setPlanning(next)}>
              <CalendarPlus size={18} /> Programar visita
            </IntelButton>
            <Link
              to={path(`recomendaciones/${next.id}`)}
              className="intel-next-details"
            >
              Ver detalles <ChevronRight size={16} />
            </Link>
          </article>
          {upcoming.length > 0 && (
            <section
              className="intel-upcoming-visits"
              aria-labelledby="upcoming-title"
            >
              <h2 id="upcoming-title">Otras sugerencias</h2>
              <ol>
                {upcoming.map((r, index) => {
                  const d = doctors.find((d) => d.id === r.doctorId)!;
                  return (
                    <li key={r.id}>
                      <Link to={path(`recomendaciones/${r.id}`)}>
                        <span className="intel-visit-order">{index + 2}</span>
                        <span className="intel-upcoming-identity">
                          <strong>{d.name}</strong>
                          <small>
                            {shortDate(r.day)} · {format12(r.time)}
                          </small>
                        </span>
                        <ChevronRight size={18} aria-hidden />
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </section>
          )}
        </>
      ) : (
        <div className="intel-mobile-done">
          <span>
            <Check size={25} />
          </span>
          <h2>Por ahora, todo revisado</h2>
          <p>Las nuevas sugerencias aparecerán aquí.</p>
          <Link
            to={path("calendario")}
            className="intel-button intel-button--secondary"
          >
            Ver visitas programadas
          </Link>
        </div>
      )}
      {accepted > 0 && next && (
        <Link to={path("calendario")} className="intel-scheduled-link">
          <CalendarDays size={16} /> {accepted}{" "}
          {accepted === 1 ? "visita programada" : "visitas programadas"}{" "}
          <ChevronRight size={16} />
        </Link>
      )}
      <ProgramRecommendationDialog
        recommendation={planning}
        onClose={() => setPlanning(null)}
        onScheduled={(name, day) => setScheduled({ name, day })}
      />
    </>
  );
}
