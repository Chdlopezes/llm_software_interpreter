"""Fase 1, conversaciones de referencia: una por situación, escritas a mano.

Las preguntas, las llamadas y las respuestas están escritas a mano sobre el corpus
real. La salida de la herramienta NO: se obtiene ejecutando obtener_documentacion.
La procedencia, los documentos esperados y el tipo de evidencia se calculan a partir
de las citas de la respuesta y del catálogo.

Usan solo vendor-stockkeeper-api y payment-promise-gateway: esos dos software deben
quedar en entrenamiento en la fase 2 para no contaminar la evaluación.

Escribe data/fase1/ejemplos_referencia.jsonl: {example_id, conversacion, caso}.
"""

from __future__ import annotations

import copy

from src.fase0.label import read_jsonl, write_jsonl
from src.fase1.catalog import CATALOG_PATH, FASE1
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase1.tool import TOOL_NAME, TOOLS, obtener_documentacion, tool_message
from src.fase1.validate import CONTRACT, citations, check_example

REFERENCE_PATH = FASE1 / "ejemplos_referencia.jsonl"
REFERENCE_SOFTWARE = ["payment-promise-gateway", "vendor-stockkeeper-api"]

PPG = "payment-promise-gateway"
VSK = "vendor-stockkeeper-api"
PPG_README = "payment-promise-gateway/latest/guide/README.md"
VSK_010_API = "vendor-stockkeeper-api/0.0.10-stock-consumer/guide/api.md"


def intro(v: str) -> str:
    return f"[vendor-stockkeeper-api/{v}/guide/introduction.md:L5-L5]"


def alerts(v: str, lines: str) -> str:
    return f"[vendor-stockkeeper-api/{v}/guide/alerts.md:{lines}]"


FORM_Q = ("En payment-promise-gateway latest, ¿en qué orden consulta el servicio la deuda y los métodos "
          "de pago al atender GET /payment_promise/form?")
FORM_A = ("Primero obtiene la deuda del usuario con getUserDebt(userId) y después los métodos de pago con "
          "getPaymentMethods(). Con ambos resultados, el servicio devuelve un PaymentPromiseFormBO al "
          "controlador, que responde con las opciones del formulario en JSON "
          f"[{PPG_README}:L120-L141].")

# Cada ejemplo: situación, idioma, historial (turnos previos), pregunta, argumentos de
# la llamada (None si no se llama), respuesta, criterios y restricciones que intervienen.
EXAMPLES = [
    {
        "id": "ref_version_explicita", "situacion": "version_explicita", "idioma": "es",
        "historial": [], "pregunta": FORM_Q, "args": {"software": PPG, "version": "latest"},
        "respuesta": FORM_A,
        "checks": ["Llama con software payment-promise-gateway y versión latest.",
                   "Indica que getUserDebt va antes que getPaymentMethods.",
                   "Menciona que el resultado es un PaymentPromiseFormBO o las opciones del formulario.",
                   "Cita el diagrama de GET /payment_promise/form."],
        "restricciones": [],
    },
    {
        "id": "ref_sin_version", "situacion": "sin_version", "idioma": "es", "historial": [],
        "pregunta": "¿Qué hace vendor-stockkeeper-api?",
        "args": {"software": VSK, "version": None},
        "respuesta": ("Las cuatro versiones documentadas (0.0.10-stock-consumer, 0.0.3-paused-seller, "
                      "0.0.6-ep-restock-man y latest) lo describen con el mismo texto: es la aplicación "
                      "responsable de actualizar el stock de los ítems del área Standard que se ofrecen en "
                      "TechZone. Tiene dos endpoints principales de reposición: uno para movimientos de stock "
                      "3PL, de cantidades menores, y otro para movimientos inbound, que pueden traer cantidades "
                      "mayores " + " ".join(intro(v) for v in ["0.0.10-stock-consumer", "0.0.3-paused-seller",
                                                                 "0.0.6-ep-restock-man", "latest"]) + "."),
        "checks": ["Llama con version=null; no pide la versión al usuario.",
                   "Dice que actualiza el stock de ítems del área Standard en TechZone.",
                   "Menciona los dos endpoints de reposición: 3PL e inbound.",
                   "Indica que la descripción no cambia entre versiones, sin atribuirla a una sola."],
        "restricciones": [],
    },
    {
        "id": "ref_en_que_version", "situacion": "en_que_version", "idioma": "en", "historial": [],
        "pregunta": "In which version of vendor-stockkeeper-api is the Operation Validation Consumer endpoint documented?",
        "args": {"software": VSK, "version": None},
        "respuesta": ("Among the available versions, only 0.0.10-stock-consumer documents it. Its api.md "
                      "includes a curl example that sends a msg object with order_id, site, order_closed_date, "
                      f"material_id, item_id, sap_sku and message_id [{VSK_010_API}:L51-L66], and a PlantUML "
                      "diagram in which, when stock is below tolerance, the item is set to status \"paused\" "
                      f"through PUT /items/{{itemId}} on API Items [{VSK_010_API}:L84-L89]. The documents of "
                      "0.0.3-paused-seller, 0.0.6-ep-restock-man and latest do not mention it. The documentation "
                      "does not say whether the endpoint was removed or simply left undocumented in those versions."),
        "checks": ["Calls with version=null.",
                   "Identifies 0.0.10-stock-consumer as the version that documents the endpoint.",
                   "Does not claim the endpoint does not exist in the other versions.",
                   "Does not state the HTTP method as a fact (the table and the example conflict).",
                   "Cites the 0.0.10-stock-consumer api.md."],
        "restricciones": [{"tipo": "no_citable", "documento": VSK_010_API, "lineas": [21, 21],
                           "motivo": "La fila de la tabla está en conflicto con el ejemplo (ver ref_contradiccion)."}],
    },
    {
        "id": "ref_comparacion_versiones", "situacion": "comparacion_versiones", "idioma": "es", "historial": [],
        "pregunta": ("¿Qué cambia entre las versiones 0.0.6-ep-restock-man y latest de vendor-stockkeeper-api en "
                     "la alerta Validation stock?"),
        "args": {"software": VSK, "version": None},
        "respuesta": ("En latest la alerta está marcada como [LOW PRIORITY] "
                      f"{alerts('latest', 'L43-L43')} y se aclara que sirve para verificar que el ítem quedó "
                      f"pausado {alerts('latest', 'L45-L46')}. El paso 2 añade cómo comprobarlo: usar el endpoint "
                      f"de ítems de la API core con el item_id y revisar \"status\" {alerts('latest', 'L50-L50')}. "
                      f"También añade una nota: la alerta puede resolverse automáticamente {alerts('latest', 'L53-L53')}. "
                      "En 0.0.6-ep-restock-man la alerta no tiene prioridad "
                      f"{alerts('0.0.6-ep-restock-man', 'L43-L43')}, y el paso 2 pide revisar el estado del ítem "
                      f"sin indicar cómo {alerts('0.0.6-ep-restock-man', 'L49-L49')}. Los pasos 1 y 3, revisar los "
                      "logs con el scope stream-prod e identificar el ítem para monitorearlo, son iguales en las dos "
                      f"{alerts('0.0.6-ep-restock-man', 'L48-L50')} {alerts('latest', 'L49-L51')}."),
        "checks": ["Llama con version=null aunque la pregunta nombre dos versiones.",
                   "Atribuye a latest la prioridad LOW PRIORITY y el uso del endpoint de ítems con item_id.",
                   "No atribuye a 0.0.6-ep-restock-man lo que solo dice latest.",
                   "Señala lo que no cambia (pasos 1 y 3).",
                   "Cita los alerts.md de ambas versiones."],
        "restricciones": [],
    },
    {
        "id": "ref_falta_software", "situacion": "falta_software", "idioma": "es", "historial": [],
        "pregunta": "¿Cómo pauso una publicación cuando el depósito tiene menos stock que el publicado?",
        "args": None,
        "respuesta": "¿Sobre qué software es tu consulta?",
        "checks": ["No llama a la herramienta.", "Pregunta por el software.", "No da una respuesta técnica."],
        "restricciones": [],
    },
    {
        "id": "ref_software_en_historial", "situacion": "software_en_historial", "idioma": "es",
        "historial": "conversacion:ref_version_explicita",
        "pregunta": "¿Y cómo consulto la promesa activa de un usuario?",
        "args": {"software": PPG, "version": "latest"},
        "respuesta": ("Con GET /payment_promise/active, enviando el identificador del usuario en el header "
                      "x-caller-id. El servicio obtiene la deuda del usuario con getUserDebt(userId) y sus promesas "
                      "con getUserPromises(userId), y devuelve un ActivePromiseBO con los detalles de la promesa "
                      f"activa [{PPG_README}:L143-L163]. El ejemplo de curl de la documentación hace esa llamada "
                      f"con el header x-caller-id [{PPG_README}:L325-L331]."),
        "checks": ["Llama con el software y la versión del turno anterior, sin volver a preguntarlos.",
                   "Indica GET /payment_promise/active y el header x-caller-id.",
                   "Describe getUserDebt y getUserPromises y el resultado ActivePromiseBO.",
                   "Cita el diagrama o el ejemplo de curl."],
        "restricciones": [],
    },
    {
        "id": "ref_evidencia_parcial", "situacion": "evidencia_parcial", "idioma": "es", "historial": [],
        "pregunta": ("En payment-promise-gateway latest, ¿con qué herramienta se recogen las métricas y qué "
                     "formato tienen las respuestas de error?"),
        "args": {"software": PPG, "version": "latest"},
        "respuesta": ("Las métricas se recogen con DataDog. Entre las principales están las tasas de éxito y de "
                      "fallo al crear promesas, las estadísticas de propuestas de condonación, los tiempos de "
                      f"respuesta de la API y las tasas de error [{PPG_README}:L522-L528]. Sobre los errores, la "
                      "documentación solo dice que el servicio usa códigos HTTP, mensajes de error detallados, "
                      f"excepciones propias y un formato de error consistente [{PPG_README}:L530-L536]. No "
                      "describe ese formato ni los códigos concretos, así que no puedo indicarlos."),
        "checks": ["Responde que las métricas se recogen con DataDog.",
                   "Declara que el formato de error no está documentado.",
                   "No inventa un formato de error ni códigos HTTP concretos.",
                   "No se abstiene en la parte que sí está documentada."],
        "restricciones": [{"tipo": "hueco", "software": PPG, "version": "latest",
                           "descripcion": "Se anuncia un formato de error común y excepciones propias, pero no se "
                                          "documentan ni el formato, ni los códigos HTTP, ni las excepciones."}],
    },
    {
        "id": "ref_sin_evidencia", "situacion": "sin_evidencia", "idioma": "es", "historial": [],
        "pregunta": "En vendor-stockkeeper-api latest, ¿qué campos devuelve Get Detail Doma?",
        "args": {"software": VSK, "version": "latest"},
        "respuesta": ("La documentación de latest solo lista Get Detail Doma en la tabla de servicios, como "
                      "GET /stock-operations/3pl/{identifierRegister} "
                      "[vendor-stockkeeper-api/latest/guide/api.md:L20-L20]. Ningún documento de esa versión "
                      "describe su respuesta ni sus campos, así que no puedo indicar qué devuelve."),
        "checks": ["Llama con versión latest.",
                   "Dice que la documentación no describe los campos de la respuesta.",
                   "No inventa campos.",
                   "No afirma que el endpoint no devuelva nada o que no exista."],
        "restricciones": [{"tipo": "hueco", "software": VSK, "version": "latest",
                           "descripcion": "El endpoint GET Get Detail Doma está en la tabla pero no tiene detalle."}],
    },
    {
        "id": "ref_contradiccion", "situacion": "contradiccion", "idioma": "es", "historial": [],
        "pregunta": "En vendor-stockkeeper-api 0.0.10-stock-consumer, ¿qué método HTTP usa Operation Validation Consumer?",
        "args": {"software": VSK, "version": "0.0.10-stock-consumer"},
        "respuesta": ("La documentación no es coherente en este punto. La tabla de servicios lo declara como GET "
                      f"en /stock-operations/3pl/validation/restock-consumer [{VSK_010_API}:L21-L21], pero el "
                      "ejemplo de la misma página lo llama con curl enviando un cuerpo JSON con --data y sin "
                      f"indicar el método [{VSK_010_API}:L53-L55]. Con esta documentación no puedo confirmar cuál "
                      "es el método correcto."),
        "checks": ["Llama con versión 0.0.10-stock-consumer.",
                   "Cita la fila de la tabla (GET) y el ejemplo con cuerpo.",
                   "Explica el conflicto sin elegir un método.",
                   "No presenta GET ni POST como un hecho confirmado."],
        "restricciones": [{"tipo": "conflicto", "documento": VSK_010_API, "lineas": [21, 21],
                           "motivo": "inconsistencia",
                           "descripcion": "La tabla lo declara como GET, pero el ejemplo envía un cuerpo con --data."}],
    },
    {
        "id": "ref_sin_documentos", "situacion": "sin_documentos", "idioma": "es", "historial": [],
        "pregunta": "¿Cómo configuro los reintentos en payment-promise-gateway 2.0?",
        "args": {"software": PPG, "version": "2.0"},
        "respuesta": ("No hay documentación de payment-promise-gateway 2.0 en el catálogo, así que no puedo "
                      "responder. Si quieres, puedo consultar la documentación de las versiones disponibles "
                      "de payment-promise-gateway."),
        "checks": ["Llama con versión 2.0 y recibe not_found.",
                   "Explica que no hay documentación para esa versión.",
                   "No inventa cómo se configuran los reintentos."],
        "restricciones": [],
    },
]


def system_message() -> dict:
    return {"role": "system", "content": (CONTRACT / "system_prompt.md").read_text(encoding="utf-8").strip()}


def turn(question: str, args: dict | None, answer: str, catalog: list[dict]) -> tuple[list[dict], dict | None]:
    msgs = [{"role": "user", "content": question}]
    if args is None:
        return msgs + [{"role": "assistant", "content": answer}], None
    result = obtener_documentacion(args["software"], args["version"], catalog)
    msgs += [
        {"role": "assistant", "content": "",
         "tool_calls": [{"type": "function", "function": {"name": TOOL_NAME, "arguments": dict(args)}}]},
        {"role": "tool", "name": TOOL_NAME, "content": tool_message(result)},
        {"role": "assistant", "content": answer},
    ]
    return msgs, result


def evidence_types(cites: list[tuple[str, int, int]], catalog: list[dict]) -> list[str]:
    by_id = {d["id"]: d for d in catalog}
    found = set()
    for doc, a, b in cites:
        for kind, ranges in by_id[doc]["tipos_evidencia"].items():
            if any(a <= r[1] and r[0] <= b for r in ranges):
                found.add(kind)
    order = ["texto", "tabla", "codigo", "diagrama", "especificacion", "formula"]
    return [k for k in order if k in found]


def build(catalog: list[dict]) -> list[dict]:
    by_id = {d["id"]: d for d in catalog}
    built: dict[str, dict] = {}
    rows = []
    for ex in EXAMPLES:
        history = ex["historial"]
        if isinstance(history, str):                      # turnos de otro ejemplo de referencia
            history = copy.deepcopy(built[history.split(":", 1)[1]]["messages"][1:])
        msgs, result = turn(ex["pregunta"], ex["args"], ex["respuesta"], catalog)
        conversation = {"tools": copy.deepcopy(TOOLS), "messages": [system_message()] + copy.deepcopy(history) + msgs}
        built[ex["id"]] = conversation
        cites = citations(ex["respuesta"])
        case = {
            "case_id": ex["id"],
            "corpus_version": catalog[0]["corpus_version"],
            "situacion": ex["situacion"],
            "idioma": ex["idioma"],
            "historial": history,
            "pregunta": ex["pregunta"],
            "expected_action": "clarification" if ex["args"] is None else "tool_call",
            "expected_tool": None if ex["args"] is None else {"name": TOOL_NAME, "arguments": dict(ex["args"])},
            "expected_document_ids": [d["id"] for d in result["documentos"]] if result else [],
            "reference_answer": ex["respuesta"],
            "answer_checks": ex["checks"],
            "tipo_evidencia": evidence_types(cites, catalog),
            "restricciones": ex["restricciones"],
            "procedencia": [{"documento": doc, "lineas": [a, b], "sha256_canonico": by_id[doc]["sha256_canonico"]}
                            for doc, a, b in cites],
        }
        rows.append({"example_id": ex["id"], "conversacion": conversation, "caso": case})
    return rows


def main() -> int:
    catalog = read_jsonl(CATALOG_PATH)
    restrictions = read_jsonl(RESTRICTIONS_PATH)
    rows = build(catalog)
    failed = 0
    for r in rows:
        errors = check_example(r["conversacion"], r["caso"], catalog, restrictions)
        for e in errors:
            print(f"  [error] {r['example_id']}: {e}")
        failed += bool(errors)
    if failed:
        raise SystemExit(f"[error] {failed} ejemplos de referencia no cumplen el contrato")
    write_jsonl(REFERENCE_PATH, rows)
    print(f"Ejemplos de referencia: {len(rows)} conversaciones válidas → {REFERENCE_PATH.relative_to(FASE1.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
