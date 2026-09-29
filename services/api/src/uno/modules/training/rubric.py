"""Rúbrica de Novamed (documento «Formato de retroalimentación»): 6 competencias × 5 = 30 puntos.

Fija en esta versión (PRD de Training, tabla 2). Cambiar pesos o anclas requiere validación de Novamed.
"""

from __future__ import annotations

from dataclasses import dataclass

RUBRIC_VERSION = "formato_v1"


@dataclass(frozen=True)
class Competency:
    id: str
    name: str
    description: str


COMPETENCIES: tuple[Competency, ...] = (
    Competency(
        "apertura", "Apertura", "Inicio profesional, breve y natural, respetando el tiempo."
    ),
    Competency(
        "sondeo",
        "Sondeo",
        "Exploró cómo prescribe hoy el médico antes de argumentar.",
    ),
    Competency(
        "parafraseo",
        "Parafraseo",
        "Resumió y validó la conducta prescriptiva antes de argumentar.",
    ),
    Competency(
        "argumentacion",
        "Argumentación",
        "Posicionó ESOMED con una diferenciación útil y conectada.",
    ),
    Competency(
        "manejo_objeciones",
        "Manejo de objeciones",
        "Respondió realmente la objeción, sin exagerar ni ponerse a la defensiva.",
    ),
    Competency("cierre", "Cierre", "Síntesis breve que deja una idea recordable."),
)
COMPETENCY_NAME = {c.id: c.name for c in COMPETENCIES}
MAX_PER_COMPETENCY = 5
MAX_TOTAL = MAX_PER_COMPETENCY * len(COMPETENCIES)  # 30

# Errores críticos (Formato §5). «compliance» bloquea el dominio aunque el puntaje sea alto (Anexo §6).
CRITICAL_ERRORS: dict[str, tuple[str, str]] = {
    "promociona_sin_explorar": ("Inició promocionando sin explorar", "ejecucion"),
    "no_identifica_prescripcion": ("No identificó cómo prescribe el médico", "ejecucion"),
    "discurso_generico": ("Dio un discurso genérico de IBP", "ejecucion"),
    "no_resalta_principio_activo": ("No resaltó el principio activo esomeprazol", "ejecucion"),
    "no_responde_objecion": ("No respondió realmente la objeción", "ejecucion"),
    "no_explica_diferenciacion": (
        "No explicó la diferenciación de ESOMED cuando fue solicitada",
        "ejecucion",
    ),
    "exagera_beneficios": ("Exageró beneficios o hizo afirmaciones absolutas", "compliance"),
    "huttling_forzado": ("Usó de forma débil o forzada la tecnología Hüttling", "compliance"),
    "cierre_sin_idea": ("Cerró sin idea clara", "ejecucion"),
    "no_adapta_especialidad": ("No adaptó el mensaje a la especialidad del médico", "ejecucion"),
    "desacredita_competidor": (
        "Desacreditó el tratamiento que el médico utiliza actualmente",
        "ejecucion",
    ),
}

# Evaluación específica del caso (Formato §4): Sí / Parcialmente / No.
CASE_CHECKS: tuple[tuple[str, str], ...] = (
    ("detecto_perfil", "¿Detectó correctamente el perfil prescriptivo del médico?"),
    (
        "identifico_barrera",
        "¿Identificó que la barrera principal era la indiferenciación entre IBP?",
    ),
    ("posiciono_principio_activo", "¿Posicionó el principio activo esomeprazol de forma clara?"),
    ("uso_huttling", "¿Utilizó adecuadamente el diferencial de tecnología Hüttling?"),
    ("diferencio_al_pedirlo", "¿Logró diferenciar ESOMED cuando el médico lo solicitó?"),
)


@dataclass(frozen=True)
class Band:
    min: int
    max: int
    level: str
    label: str


# Bandas de interpretación (Formato §6).
BANDS: tuple[Band, ...] = (
    Band(26, 30, "sobresaliente", "Desempeño sobresaliente"),
    Band(20, 25, "bueno", "Buen desempeño con oportunidades de mejora"),
    Band(14, 19, "intermedio", "Desempeño intermedio, requiere refuerzo"),
    Band(0, 13, "deficiente", "Desempeño deficiente, requiere reentrenamiento"),
)


def band_for(total: int) -> Band:
    return next((b for b in BANDS if b.min <= total <= b.max), BANDS[-1])


# Retroalimentación modelo por banda (Formato §9).
BAND_FEEDBACK = {
    "sobresaliente": (
        "Lograste identificar correctamente que el médico ya utiliza IBP, pero sin una preferencia "
        "definida, y construiste una diferenciación clara para ESOMED. Posicionaste adecuadamente el "
        "principio activo esomeprazol y respondiste bien la objeción usando el diferencial de "
        "tecnología Hüttling de forma pertinente."
    ),
    "bueno": (
        "La visita estuvo bien estructurada y lograste explorar antes de argumentar. Sin embargo, la "
        "diferenciación de ESOMED pudo haber sido más concreta, especialmente al responder la "
        "objeción del médico frente a la similitud entre los IBP."
    ),
    "intermedio": (
        "Tuviste elementos correctos en la visita, pero faltó profundizar en cómo prescribe el médico "
        "y aterrizar mejor el valor diferencial de ESOMED. La argumentación fue útil, aunque todavía "
        "algo general."
    ),
    "deficiente": (
        "La visita no logró identificar la verdadera barrera del escenario, que era la "
        "indiferenciación frente a los IBP. La respuesta a la objeción fue insuficiente y no se "
        "construyó una razón clara para diferenciar ESOMED."
    ),
}

# Recomendaciones de entrenamiento posterior (Formato §10).
REINFORCEMENT_AREA = {
    "apertura": "apertura de visita",
    "sondeo": "identificación de necesidad",
    "parafraseo": "parafraseo",
    "argumentacion": "diferenciación de ESOMED",
    "manejo_objeciones": "manejo de objeciones",
    "cierre": "cierre breve y recordable",
}

# Práctica concreta para el próximo intento (prototipo de Sangil, `training.js`).
REMEDIATION = {
    "apertura": (
        "Practica una apertura de máximo dos frases: reconoce el tiempo y formula una pregunta útil."
    ),
    "sondeo": (
        "Prepara dos preguntas: una para conocer qué usa y otra para descubrir por qué lo elige."
    ),
    "parafraseo": (
        "Resume en una frase la conducta del médico antes de presentar cualquier argumento."
    ),
    "argumentacion": (
        "Une necesidad + paciente + ESOMED. Elimina adjetivos como «excelente» o «superior»."
    ),
    "manejo_objeciones": (
        "Responde en tres pasos: reconoce, pregunta o precisa, y conecta con un punto concreto."
    ),
    "cierre": "Cierra en una frase con producto, perfil de paciente y una expectativa realista.",
}
