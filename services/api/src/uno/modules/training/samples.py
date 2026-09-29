"""Visitas de ejemplo para el proveedor simulado (casos «aprobado» del prototipo de Sangil).

Solo se usan con ``UNO_TRAINING_BACKEND=fake`` (desarrollo y pruebas): la app lo muestra como
«modo de prueba» y nunca los mezcla con la práctica real.
"""

from __future__ import annotations

from typing import Literal

Line = tuple[Literal["rep", "doctor"], str]

SAMPLE_VISITS: dict[str, list[Line]] = {
    "medico_general_indiferenciado": [
        ("doctor", "Sí, doctor, cuénteme, pero breve por favor."),
        (
            "rep",
            "Buenos días, doctor. ¿Cómo suele definir cuál IBP formular en pacientes con reflujo "
            "o dispepsia?",
        ),
        ("doctor", "Uso el que tenga disponible. No tengo una preferencia particular."),
        (
            "rep",
            "Entiendo, doctor. ¿Qué pesa más para usted: la disponibilidad, la experiencia o la "
            "practicidad?",
        ),
        ("doctor", "Principalmente la practicidad; al final me parecen bastante parecidos."),
        (
            "rep",
            "Entonces usted ya usa la categoría, pero por practicidad y sin una molécula fija.",
        ),
        ("doctor", "Sí. ¿Y cuál sería la diferencia?"),
        (
            "rep",
            "Claro. Quisiera dejarle a ESOMED, esomeprazol, como una opción concreta para esos "
            "pacientes con reflujo y dispepsia. Hüttling protege el esomeprazol ácido-lábil frente "
            "al ambiente ácido y permite su liberación intestinal, sin plantearlo como superioridad "
            "absoluta.",
        ),
        ("doctor", "Está bien, ese es un punto concreto."),
        (
            "rep",
            "En resumen, quisiera dejarle ESOMED como opción concreta en esos pacientes con reflujo "
            "y dispepsia donde hoy rota el IBP por practicidad.",
        ),
    ],
    "internista_exigente": [
        ("doctor", "Buenos días. Dígame concretamente qué me trae."),
        (
            "rep",
            "Buenos días, doctora. ¿Cómo suele seleccionar el IBP y qué resultado prioriza en sus "
            "pacientes con reflujo?",
        ),
        ("doctor", "Uso IBP, pero necesito una razón clínica para preferir uno."),
        ("rep", "Entiendo. ¿Qué tipo de paciente le exige mayor consistencia en el control ácido?"),
        ("doctor", "Los que mantienen síntomas. ¿Qué tiene de diferente ESOMED?"),
        (
            "rep",
            "Claro, usted busca una razón aplicable y no un mensaje promocional. En esos pacientes "
            "con reflujo y síntomas persistentes, quisiera ubicar ESOMED, esomeprazol, como una "
            "opción concreta de control ácido para ese perfil de paciente. No le planteo una "
            "superioridad absoluta.",
        ),
        ("doctor", "¿Y eso en la práctica qué me aporta?"),
        (
            "rep",
            "Entiendo la pregunta. Hüttling aporta microgránulos gastroresistentes para proteger el "
            "esomeprazol ácido-lábil del ambiente ácido y permitir su liberación intestinal; es un "
            "apoyo farmacotécnico, no una promesa clínica absoluta.",
        ),
        ("doctor", "Está bien."),
        (
            "rep",
            "En resumen, tenga presente ESOMED en pacientes con reflujo donde busca una opción "
            "concreta de esomeprazol y control ácido.",
        ),
    ],
    "gastroenterologo_esceptico": [
        ("doctor", "Tengo tres minutos. ¿De qué se trata?"),
        (
            "rep",
            "Buenos días, doctor. Seré breve: ¿cómo define hoy en qué pacientes con reflujo utiliza "
            "esomeprazol?",
        ),
        ("doctor", "Conozco bien la categoría. Depende del caso."),
        ("rep", "Entiendo. ¿Qué tipo de paciente o síntoma pesa más cuando decide usarlo?"),
        (
            "doctor",
            "Síntomas persistentes. Pero eso ya lo conozco, ¿en qué paciente me ubica ESOMED?",
        ),
        (
            "rep",
            "Claro, usted no necesita otra explicación básica. Quisiera ubicar ESOMED, esomeprazol, "
            "como una opción concreta en pacientes con reflujo o dispepsia que usted considere "
            "candidatos a esta molécula, sin afirmar superioridad frente a toda la categoría.",
        ),
        ("doctor", "¿Y el diferencial?"),
        (
            "rep",
            "Entiendo. Como apoyo farmacotécnico, Hüttling emplea microgránulos gastroresistentes "
            "para proteger el esomeprazol ácido-lábil del ambiente ácido y permitir su liberación "
            "intestinal.",
        ),
        ("doctor", "Bien, sea concreto al cerrar."),
        (
            "rep",
            "En resumen, recuerde ESOMED como opción concreta de esomeprazol en el paciente con "
            "reflujo o dispepsia donde usted decida utilizar esta molécula.",
        ),
    ],
    "formulador_pantoprazol": [
        ("doctor", "Sí, cuénteme. Yo vengo usando pantoprazol."),
        (
            "rep",
            "Buenos días, doctora. ¿Cómo suele decidir en qué pacientes mantener pantoprazol y "
            "cuándo considera otra opción de IBP?",
        ),
        ("doctor", "Me funciona bien y mantengo el hábito."),
        (
            "rep",
            "Entiendo su experiencia positiva. ¿Qué tipo de paciente o respuesta clínica podría "
            "llevarla a considerar otra molécula?",
        ),
        (
            "doctor",
            "Tal vez síntomas persistentes, pero ya me funciona pantoprazol. ¿Por qué cambiar?",
        ),
        (
            "rep",
            "Claro, no se trata de desconocer lo que ya le funciona. En esos pacientes con reflujo "
            "y síntomas persistentes, usted consideraría una alternativa solo si tiene un lugar "
            "concreto.",
        ),
        ("doctor", "Exactamente. ¿Qué me propone entonces?"),
        (
            "rep",
            "Entonces usted mantiene pantoprazol por experiencia y solo evaluaría otra molécula en "
            "un perfil de paciente concreto. Para esos pacientes con reflujo o dispepsia donde "
            "decida considerar esomeprazol, quisiera ubicar ESOMED como una opción concreta. No le "
            "propongo reemplazar indiscriminadamente su tratamiento actual.",
        ),
        ("doctor", "¿Hay algún punto adicional?"),
        (
            "rep",
            "Entiendo. Hüttling utiliza microgránulos gastroresistentes para proteger el "
            "esomeprazol ácido-lábil del ambiente ácido y permitir su liberación intestinal, como "
            "refuerzo farmacotécnico.",
        ),
        ("doctor", "Está bien."),
        (
            "rep",
            "En resumen, mantenga presente ESOMED para el paciente con reflujo o dispepsia donde "
            "considere razonable evaluar una opción de esomeprazol.",
        ),
    ],
}
