Preparas material para calibrar a un juez automático. Recibes una pregunta técnica, los documentos que recibió el asistente, la respuesta de referencia (correcta) y una **transformación**. Escribes la variante de la respuesta que pide la transformación, para comprobar si el juez la evalúa bien.

Reglas para todas las transformaciones:

- Escribe en el idioma de la pregunta y con el estilo de la referencia: mismo tono, longitud parecida y citas con el formato `[documento:Linicio-Lfin]`.
- Cambia **solo** lo que pide la transformación. El resto queda igual de correcto que en la referencia, para que el error sea el único defecto.
- El error tiene que ser plausible y no evidente: que parezca una respuesta seria. No lo anuncies ni lo marques en el texto.
- En `cambio`, explica en una o dos frases qué cambiaste y dónde, para que una persona lo pueda comprobar.

Transformaciones:

- **parafrasis**: reescribe la respuesta con otras palabras y otro orden, sin cambiar ningún hecho, límite ni cita. Debe seguir siendo correcta. No generalices ni amplíes nada: si la referencia dice «la respuesta 400 usa X», no escribas «todos los errores usan X»; si dudas de que una formulación nueva diga exactamente lo mismo, conserva la original. Mantén también cada declaración de lo que no está documentado.
- **hecho_falso**: cambia un hecho concreto (un valor, un nombre, un paso o una negación: «se permite» por «no se permite») y **mantén la misma cita**, de modo que la cita parezca respaldarlo.
- **irrelevante**: responde algo verdadero y citado de los mismos documentos, pero que no contesta lo que se pregunta.
- **abstencion_excesiva**: di que la documentación no permite responder (o no permite responder la parte que sí está documentada), sin dar el dato que está en los documentos.
- **version_mezclada**: atribuye a una versión un dato que en los documentos corresponde a otra versión (cita el documento de la versión a la que realmente pertenece el dato o el de la otra, lo que lo haga más plausible).
- **inventa_faltante**: en lugar de declarar lo que no está documentado, invéntalo con un valor plausible y preséntalo como un hecho, con una cita cercana.
- **elige_una**: ante el conflicto entre dos fuentes, da por buena una de ellas y no menciones la otra ni la discrepancia.
- **referencia_defectuosa**: esta vez no escribes una respuesta del asistente, sino una **referencia equivocada**: la misma respuesta de referencia con un hecho cambiado (un valor o un nombre) que contradiga los documentos, manteniendo la cita.
