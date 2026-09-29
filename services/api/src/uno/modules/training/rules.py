"""Evaluador por reglas: califica una visita sin LLM (port fiel de ``heuristic.js`` del prototipo).

Determinista, gratis e instantáneo. Es la **calificación preliminar** mientras no haya juez LLM
(doc 04 §5.9) y, después, la red de seguridad y las señales que el juez no puede ignorar.
Califica más duro que un evaluador humano: el diálogo modelo «regular» queda en 7/30 cuando el
Anexo espera 14–19. Por eso la app la presenta como preliminar.

La transcripción llega del reconocimiento de voz: las palabras clave aceptan variantes
(«Hutlin», «Jutlin») y se comparan sin tildes ni mayúsculas.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from uno.modules.training.rubric import COMPETENCIES, REINFORCEMENT_AREA

RULES_VERSION = "reglas_v1"
DEFAULT_IMPROVEMENT = "Afina el nivel de detalle del argumento."

Role = Literal["rep", "doctor"]


@dataclass(frozen=True)
class Turn:
    role: Role
    text: str


def norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in decomposed if not 0x300 <= ord(ch) <= 0x36F)


def has(text: str, words: tuple[str, ...]) -> bool:
    haystack = norm(text)
    return any(norm(w) in haystack for w in words)


def count_matches(text: str, words: tuple[str, ...]) -> int:
    haystack = norm(text)
    return sum(1 for w in words if norm(w) in haystack)


def _words(text: str) -> int:
    return len(text.split())


# ------------------------------------------------------------------------- señales del brief

SALUDO = ("buenos dias", "buenas tardes", "doctor", "gracias por", "un momento")
PREGUNTAS_EXPLORACION = (
    "como suele",
    "como define",
    "como esta manejando",
    "como selecciona",
    "como decide",
    "que pesa mas",
    "que criterio",
    "suele manejar",
    "rota segun",
    "tiene alguna preferencia",
    "que tipo de paciente",
    "con que frecuencia",
    "que valora",
    "que le importa mas",
)
PARAFRASEO = (
    "entiendo, doctor",
    "o sea que",
    "entonces, doctor",
    "entonces usted",
    "si le entiendo",
    "lo que me dice",
    "veo que",
    "usted ya utiliza",
    "usted ya usa",
    "usted ya maneja",
    "en su caso",
    "perfecto, doctor",
    "claro, doctor, entonces",
)
ARGUMENTACION_BUENA = (
    "opcion concreta",
    "opcion clara",
    "bien ubicada",
    "bien ubicado",
    "recordable",
    "dentro de su practica",
    "en su practica diaria",
    "posicionar",
    "espacio concreto",
    "razon para recordar",
    "perfil de paciente",
    "en esos pacientes",
)
CLINICO = ("reflujo", "dispepsia", "pirosis", "regurgitacion", "digestivos altos")
PRINCIPIO_ACTIVO = ("esomeprazol",)
# «Hüttling» llega escrito de muchas formas desde el reconocimiento de voz.
HUTTLING = (
    "huttling",
    "hüttling",
    "huttlin",
    "hutling",
    "hutlin",
    "jutlin",
    "huettlin",
    "microgranulos",
    "gastroresistente",
    "gastrorresistente",
)
HUTTLING_BIEN_CONECTADO = (
    "acido labil",
    "acido-labil",
    "ambiente acido",
    "medio acido",
    "ph acido",
    "liberacion intestinal",
    "proteger el esomeprazol",
    "proteger el activo",
)
GENERICAS = (
    "es excelente",
    "es muy bueno",
    "muy buen ibp",
    "es una gran alternativa",
    "funciona muy bien",
    "es buenisimo",
    "tenga presente",
    "le queria recordar los beneficios",
    "muy util",
    "tecnologia muy avanzada",
)
ABSOLUTAS = (
    "95%",
    "mas del 95",
    "absorcion total",
    "garantiza",
    "es mejor que los demas",
    "superior a todos",
    "el mejor del mercado",
    "no se inactiva",
    "siempre funciona",
    "ninguno se compara",
)
RECONOCIMIENTO_OBJECION = (
    "entiendo",
    "claro",
    "totalmente",
    "de acuerdo",
    "es una percepcion",
    "eso pasa mucho",
    "no se trata de desconocer",
    "tiene razon",
)
CIERRE = (
    "en resumen",
    "quisiera dejarle",
    "quisiera que recuerde",
    "para cerrar",
    "me gustaria dejarle",
    "que le quede",
    "lo dejo con",
    "tenga en cuenta a esomed para",
)
PRODUCTO = ("esomed",)
DESCREDITA_COMPETIDOR = (
    "pantoprazol no sirve",
    "pantoprazol es malo",
    "pantoprazol es inferior",
    "deje de usar pantoprazol",
    "no deberia usar pantoprazol",
    "esomeprazol es mejor que pantoprazol",
)
OBJECION_MEDICO = (
    "parecidos",
    "parecido",
    "cualquiera",
    "cualquier ibp",
    "con cualquier",
    "el que tenga",
    "no tengo una preferencia",
    "no tengo preferencia",
    "ya lo conozco",
    "eso ya lo",
    "que tendria de diferente",
    "que tiene de diferente",
    "cual seria la diferencia",
    "cual es la diferencia",
    "por que cambiar",
    "por que tendria que",
    "ya me funciona",
    "ya vengo usando",
    "ya vengo manejando",
    "que me aporta",
    "diferencial real",
    "en que paciente",
)


@dataclass
class Signals:
    """Lo que las reglas observan en la transcripción (índices sobre los turnos del visitador)."""

    rep_turns: int
    doctor_turns: int
    rep_words: int
    greeting: bool
    questions: int
    exploratory_questions: int
    first_exploration: int
    first_product: int
    first_huttling: int
    promotes_without_exploring: bool
    paraphrases: int
    good_argument_hits: int
    mentions_clinical: bool
    mentions_molecule: bool
    mentions_product: bool
    mentions_huttling: bool
    huttling_connected: bool
    huttling_early: bool
    generic_phrases: int
    absolute_claims: int
    objections_total: int
    objections_answered: int
    objections_acknowledged: int
    close_with_synthesis: bool
    close_with_patient: bool
    last_turn_words: int
    first_turn_words: int
    disparages_competitor: bool
    objection_pairs: list[tuple[int, int | None]] = field(default_factory=list)


def analyze(turns: list[Turn]) -> Signals:
    rep = [t for t in turns if t.role == "rep"]
    all_rep = " \n ".join(t.text for t in rep)
    first = rep[0].text if rep else ""
    last = rep[-1].text if rep else ""

    def first_index(predicate) -> int:  # type: ignore[no-untyped-def]
        return next((i for i, t in enumerate(rep) if predicate(t.text)), -1)

    first_exploration = first_index(lambda s: has(s, PREGUNTAS_EXPLORACION) or "?" in s)
    first_product = first_index(lambda s: has(s, PRODUCTO))
    first_huttling = first_index(lambda s: has(s, HUTTLING))
    promotes = first_product != -1 and (
        first_exploration == -1 or first_product < first_exploration
    )

    # Objeciones del médico y la respuesta siguiente del visitador (índices globales de turno).
    pairs: list[tuple[int, int | None]] = []
    for i, turn in enumerate(turns):
        if turn.role != "doctor" or not has(turn.text, OBJECION_MEDICO):
            continue
        answer = next((j for j in range(i + 1, len(turns)) if turns[j].role == "rep"), None)
        pairs.append((i, answer))

    def answer_text(pair: tuple[int, int | None]) -> str:
        return turns[pair[1]].text if pair[1] is not None else ""

    answered = sum(
        1
        for p in pairs
        if answer_text(p)
        and has(answer_text(p), RECONOCIMIENTO_OBJECION)
        and (
            has(answer_text(p), ARGUMENTACION_BUENA)
            or has(answer_text(p), HUTTLING)
            or has(answer_text(p), CLINICO)
        )
    )
    acknowledged = sum(
        1 for p in pairs if answer_text(p) and has(answer_text(p), RECONOCIMIENTO_OBJECION)
    )
    return Signals(
        rep_turns=len(rep),
        doctor_turns=sum(1 for t in turns if t.role == "doctor"),
        rep_words=_words(all_rep),
        greeting=has(first, SALUDO),
        questions=sum(1 for t in rep if "?" in t.text),
        exploratory_questions=sum(1 for t in rep if has(t.text, PREGUNTAS_EXPLORACION)),
        first_exploration=first_exploration,
        first_product=first_product,
        first_huttling=first_huttling,
        promotes_without_exploring=promotes,
        paraphrases=sum(1 for t in rep if has(t.text, PARAFRASEO)),
        good_argument_hits=count_matches(all_rep, ARGUMENTACION_BUENA),
        mentions_clinical=has(all_rep, CLINICO),
        mentions_molecule=has(all_rep, PRINCIPIO_ACTIVO),
        mentions_product=has(all_rep, PRODUCTO),
        mentions_huttling=first_huttling != -1,
        huttling_connected=has(all_rep, HUTTLING_BIEN_CONECTADO),
        huttling_early=first_huttling != -1
        and (first_exploration == -1 or first_huttling <= first_exploration),
        generic_phrases=count_matches(all_rep, GENERICAS),
        absolute_claims=count_matches(all_rep, ABSOLUTAS),
        objections_total=len(pairs),
        objections_answered=answered,
        objections_acknowledged=acknowledged,
        close_with_synthesis=has(last, CIERRE),
        close_with_patient=has(last, CLINICO) or has(last, ("pacientes",)),
        last_turn_words=_words(last),
        first_turn_words=_words(first),
        disparages_competitor=has(all_rep, DESCREDITA_COMPETIDOR),
        objection_pairs=pairs,
    )


# ------------------------------------------------------------------------- puntaje por competencia


def _clamp(value: int) -> int:
    return max(0, min(5, value))


def score_opening(a: Signals) -> tuple[int, str]:
    s, c = 2, []
    if a.greeting:
        s += 1
        c.append("Abriste con un saludo profesional.")
    else:
        c.append("Faltó un saludo claro al inicio.")
    if a.first_exploration == 0:
        s += 2
        c.append(
            "Entraste preguntando por su práctica en lugar de promocionar: es la apertura correcta."
        )
    elif a.promotes_without_exploring:
        s -= 2
        c.append("Entraste directamente al producto sin preguntar nada primero.")
    if a.first_turn_words > 90:
        s -= 1
        c.append("La apertura fue larga; el médico tiene poco tiempo.")
    return _clamp(s), " ".join(c)


def score_probing(a: Signals) -> tuple[int, str]:
    c = []
    if a.exploratory_questions >= 2:
        s = 5
        c.append("Exploraste con varias preguntas sobre cómo prescribe hoy.")
    elif a.exploratory_questions == 1:
        s = 3
        c.append("Hiciste una pregunta exploratoria, pero te quedaste corto: faltó profundizar.")
    elif a.questions >= 1:
        s = 2
        c.append("Preguntaste, pero no indagaste específicamente cómo selecciona el IBP.")
    else:
        s = 0
        c.append("No exploraste cómo prescribe el médico. Es el error central de este escenario.")
    if a.promotes_without_exploring:
        s = _clamp(s - 2)
        c.append("Además, mencionaste el producto antes de explorar.")
    return _clamp(s), " ".join(c)


def score_paraphrase(a: Signals) -> tuple[int, str]:
    if a.paraphrases >= 2:
        return 5, "Resumiste y validaste lo que dijo el médico antes de argumentar."
    if a.paraphrases == 1:
        return 3, (
            "Hubo un parafraseo, pero podías haber ordenado mejor la necesidad antes de entrar "
            "al argumento."
        )
    return 1, "No parafraseaste. El médico no sintió que lo escucharas antes de argumentar."


def score_argument(a: Signals) -> tuple[int, str]:
    s, c = 1, []
    if a.mentions_molecule:
        s += 1
        c.append("Posicionaste el principio activo esomeprazol.")
    else:
        c.append("No resaltaste el principio activo esomeprazol.")
    if a.mentions_clinical:
        s += 1
        c.append("Conectaste con reflujo y dispepsia.")
    else:
        c.append("Faltó aterrizar el mensaje en reflujo y dispepsia.")
    if a.good_argument_hits >= 2:
        s += 2
        c.append("Construiste un posicionamiento concreto y recordable.")
    elif a.good_argument_hits == 1:
        s += 1
    else:
        c.append("La argumentación quedó general, sin un espacio concreto para ESOMED.")
    if a.generic_phrases >= 1:
        s -= 1
        c.append("Usaste frases promocionales vacías que el médico no compra.")
    if a.absolute_claims >= 1:
        s -= 2
        c.append("Hiciste afirmaciones absolutas o cifras sin soporte.")
    return _clamp(s), " ".join(c)


def score_objections(a: Signals) -> tuple[int, str]:
    if a.objections_total == 0:
        return (1 if a.promotes_without_exploring else 2), (
            "El médico no llegó a objetar con claridad, así que no hay evidencia directa de "
            "manejo de objeciones en esta visita."
        )
    c = []
    ratio = a.objections_answered / a.objections_total
    ratio_ack = a.objections_acknowledged / a.objections_total
    if ratio >= 0.8:
        s = 5
        c.append(
            "Reconociste la percepción del médico y llevaste la conversación a un punto concreto."
        )
    elif ratio >= 0.5:
        s = 3
        c.append("Respondiste parcialmente las objeciones; alguna quedó sin cerrar.")
    elif ratio_ack >= 0.5:
        s = 2
        c.append(
            "Reconociste la objeción sin ponerte a la defensiva, pero no reconduciste hacia un "
            "punto concreto de posicionamiento."
        )
    else:
        s = 1
        c.append("No respondiste realmente la objeción del médico.")
    if a.mentions_huttling and a.huttling_connected and not a.huttling_early:
        s += 1
        c.append(
            "Usaste la tecnología Hüttling en el momento correcto y conectada al carácter "
            "ácido-lábil de la molécula."
        )
    elif a.huttling_early:
        s -= 1
        c.append(
            "Mencionaste Hüttling demasiado pronto: sonó a folleto en vez de a diferenciación."
        )
    elif a.mentions_huttling and not a.huttling_connected:
        c.append(
            "Mencionaste Hüttling pero sin conectarlo con la protección del activo frente al "
            "medio ácido."
        )
    if a.absolute_claims >= 1:
        s -= 1
        c.append("Al defender el producto exageraste.")
    return _clamp(s), " ".join(c)


def score_close(a: Signals) -> tuple[int, str]:
    s, c = 1, []
    if a.close_with_synthesis:
        s += 2
        c.append("Cerraste con una síntesis explícita.")
    else:
        c.append("No hiciste una síntesis final.")
    if a.close_with_patient:
        s += 1
        c.append("Dejaste el producto ubicado en un perfil de paciente.")
    else:
        c.append("Faltó anclar el cierre a un perfil de paciente concreto.")
    if 0 < a.last_turn_words <= 60:
        s += 1
        c.append("El cierre fue breve.")
    elif a.last_turn_words > 90:
        s -= 1
        c.append("El cierre fue largo: repetiste el argumento en vez de resumirlo.")
    return _clamp(s), " ".join(c)


SCORERS = {
    "apertura": score_opening,
    "sondeo": score_probing,
    "parafraseo": score_paraphrase,
    "argumentacion": score_argument,
    "manejo_objeciones": score_objections,
    "cierre": score_close,
}


def detect_errors(a: Signals, scenario_slug: str) -> list[str]:
    errors = []
    if a.promotes_without_exploring:
        errors.append("promociona_sin_explorar")
    if a.exploratory_questions == 0:
        errors.append("no_identifica_prescripcion")
    if a.generic_phrases >= 2:
        errors.append("discurso_generico")
    if not a.mentions_molecule:
        errors.append("no_resalta_principio_activo")
    if a.objections_total > 0 and a.objections_answered == 0:
        errors.append("no_responde_objecion")
    if a.absolute_claims >= 1:
        errors.append("exagera_beneficios")
    if a.mentions_huttling and (a.huttling_early or not a.huttling_connected):
        errors.append("huttling_forzado")
    if not a.close_with_synthesis:
        errors.append("cierre_sin_idea")
    if scenario_slug == "gastroenterologo_esceptico" and (
        not a.mentions_clinical or not a.close_with_patient
    ):
        errors.append("no_adapta_especialidad")
    if scenario_slug == "formulador_pantoprazol" and a.disparages_competitor:
        errors.append("desacredita_competidor")
    return errors


def case_checks(a: Signals) -> dict[str, str]:
    def tri(ok: bool, partial: bool) -> str:
        return "si" if ok else "parcial" if partial else "no"

    return {
        "detecto_perfil": tri(a.exploratory_questions >= 2, a.exploratory_questions == 1),
        "identifico_barrera": tri(
            a.paraphrases >= 1 and a.good_argument_hits >= 1, a.paraphrases >= 1
        ),
        "posiciono_principio_activo": tri(
            a.mentions_molecule and a.mentions_clinical, a.mentions_molecule
        ),
        "uso_huttling": tri(
            a.mentions_huttling and a.huttling_connected and not a.huttling_early,
            a.mentions_huttling,
        ),
        "diferencio_al_pedirlo": tri(
            a.objections_total > 0 and a.objections_answered == a.objections_total,
            a.objections_answered > 0,
        ),
    }


def key_moment(turns: list[Turn], a: Signals, errors: list[str]) -> dict[str, object] | None:
    """La frase exacta del visitador que más pesó en el resultado (la primera falla importante)."""
    rep_indexes = [i for i, t in enumerate(turns) if t.role == "rep"]

    def rep_turn(k: int) -> int | None:
        return rep_indexes[k] if 0 <= k < len(rep_indexes) else None

    def first_with(words: tuple[str, ...]) -> int | None:
        return next((i for i in rep_indexes if has(turns[i].text, words)), None)

    finders: list[tuple[str, int | None, str]] = [
        ("exagera_beneficios", first_with(ABSOLUTAS), "Afirmación absoluta o cifra sin soporte."),
        (
            "desacredita_competidor",
            first_with(DESCREDITA_COMPETIDOR),
            "Desacreditaste el tratamiento que el médico ya usa.",
        ),
        (
            "promociona_sin_explorar",
            rep_turn(a.first_product),
            "Presentaste el producto antes de preguntar cómo prescribe.",
        ),
        (
            "huttling_forzado",
            rep_turn(a.first_huttling),
            "Hüttling apareció antes de detectar la indiferenciación o sin conectarlo con la "
            "molécula.",
        ),
        ("discurso_generico", first_with(GENERICAS), "Frase promocional genérica."),
        (
            "no_responde_objecion",
            next((p[1] for p in a.objection_pairs if p[1] is not None), None),
            "Esta respuesta no reconoció la objeción ni la llevó a un punto concreto.",
        ),
        (
            "cierre_sin_idea",
            rep_indexes[-1] if rep_indexes else None,
            "El cierre no dejó una síntesis.",
        ),
    ]
    for error, index, why in finders:
        if error in errors and index is not None:
            return {"turn": index + 1, "quote": turns[index].text, "why": why}
    return None


@dataclass
class RulesResult:
    scores: dict[str, int]
    comments: dict[str, str]
    errors: list[str]
    checks: dict[str, str]
    strengths: list[str]
    improvements: list[str]
    areas: list[str]
    recommendation: str
    key_moment: dict[str, object] | None
    signals: Signals


def evaluate(turns: list[Turn], scenario_slug: str) -> RulesResult:
    a = analyze(turns)
    scores: dict[str, int] = {}
    comments: dict[str, str] = {}
    for competency in COMPETENCIES:
        scores[competency.id], comments[competency.id] = SCORERS[competency.id](a)
    errors = detect_errors(a, scenario_slug)
    strengths = [
        f"{REINFORCEMENT_AREA[c.id].capitalize()}: {comments[c.id]}"
        for c in COMPETENCIES
        if scores[c.id] >= 4
    ]
    improvements = [
        f"{REINFORCEMENT_AREA[c.id].capitalize()}: {comments[c.id]}"
        for c in COMPETENCIES
        if scores[c.id] <= 2
    ]
    areas = [c.id for c in COMPETENCIES if scores[c.id] <= 3]
    if "sondeo" in areas:
        recommendation = (
            "Para mejorar, no nombres el producto hasta haber hecho al menos dos preguntas sobre "
            "cómo selecciona el IBP."
        )
    elif "parafraseo" in areas:
        recommendation = "Para mejorar, parafrasea lo que dice el médico antes de argumentar."
    elif "cierre" in areas:
        recommendation = (
            "Para mejorar, cierra con una sola frase que ubique ESOMED en un perfil de paciente "
            "concreto."
        )
    else:
        recommendation = (
            "Refuerza la conexión entre lo que descubres en la exploración y el diferencial de "
            "Hüttling."
        )
    return RulesResult(
        scores=scores,
        comments=comments,
        errors=errors,
        checks=case_checks(a),
        strengths=strengths or ["Completaste la visita de principio a fin."],
        improvements=improvements or [DEFAULT_IMPROVEMENT],
        areas=areas,
        recommendation=recommendation,
        key_moment=key_moment(turns, a, errors),
        signals=a,
    )
