# CLAUDE.md — Mockup React: Sistema de Comedor y Nutrición Hospitalaria (Módulo Personal)

## Contexto

Este es un **mockup de alta fidelidad** de la aplicación principal del Sistema de Comedor y
Nutrición Hospitalaria, cuyo usuario final es la **jefa de nutrición** del hospital. El stack
de producción ya decidido para este proyecto es **React (frontend) + FastAPI (backend) +
MySQL (base de datos)** — este mockup se construye directamente en React porque es lo que se
usará en producción, no es un descarte.

Por ahora, esta tarea cubre **únicamente el Módulo Personal / Comensales** (control de acceso
al comedor del personal médico, residentes, internos, policías y técnicos). El módulo de
Pacientes existe en el plan del sistema pero no se implementa todavía en este mockup.

## Diferencia respecto al prototipo anterior

Ya existe un prototipo previo construido como un único archivo HTML monolítico (hecho con otro
agente, sin React), que sirvió para validar el flujo de interacción. Esta tarea es distinta:
se construye con **componentes de React reales** (function components + hooks), como base
para lo que eventualmente consumirá la API real de FastAPI — no es un archivo único, es una
estructura de proyecto React normal.

## Stack técnico

- React con Vite (setup estándar, rápido). Si tienes una razón de peso para usar otra
  herramienta de build, está bien, pero Vite es la opción por defecto esperada.
- Componentes funcionales con hooks (`useState`, `useEffect` donde corresponda). Nada de
  componentes de clase.
- **Conexión a backend real (FastAPI).** El acceso HTTP está centralizado en
  `src/api.js`, que actúa como cliente de la API y adaptador de datos para la UI.
- Para el gráfico del dashboard, usa **Recharts** (librería de gráficos hecha específicamente
  para React, más idiomática que Chart.js en este contexto).
- Para la lectura de Excel, usa **SheetJS (`xlsx`)** vía `npm install xlsx`.

## Estructura funcional (sidebar + main)

- **Sidebar** fijo a la izquierda con estos ítems:
  1. Pantalla en vivo (funcional, la más importante)
  2. Dashboard / Reportes (funcional)
  3. Importar Excel (funcional)
  4. Pacientes — **deshabilitado visualmente, marcado como "Próximamente"** (clic no hace
     nada, o muestra un mensaje de que está en desarrollo). Esto es intencional: comunica el
     alcance completo del sistema a la jefa de nutrición aunque todavía no esté construido.
- **Header** con el nombre del sistema: "Sistema de Comedor y Nutrición Hospitalaria".
- Layout limpio y moderno tipo dashboard administrativo, con buen espaciado y jerarquía visual
  clara.

## Sección 1 — Pantalla en vivo (prioridad máxima)

- Un botón **"Simular marcación"** que elige una persona al azar de una lista de prueba (8-10
  personas ficticias, cada una con nombre, categoría — Médico, Residente, Interno, Policía,
  Técnico — y si ya marcó su comida de hoy) y dispara el evento como si el biométrico real
  acabara de leer su huella.
- Al dispararse el evento, con una animación breve:
  - Nombre completo de la persona.
  - Check verde grande si la marcación es válida, X roja grande si no.
  - Flash de color (verde/rojo) breve cubriendo toda el área `main`, sincronizado con el
    resultado.
  - Gauge o barra circular de "Raciones restantes" que baja en 1 con cada marcación válida,
    con transición animada suave (no un salto brusco).
- Reglas de validación (simuladas, sin lógica de negocio real):
  - Si la persona ya marcó hoy esa misma comida → X ("Ya registró su comida de hoy").
  - Si no quedan raciones disponibles para el turno → X ("No quedan raciones disponibles").
  - Cualquier otro caso → check verde.
- El botón "Simular marcación" permanece siempre visible, sin necesitar scroll.

## Sección 2 — Dashboard / Reportes

- Gráfico de barras (Recharts) de raciones consumidas hoy por categoría: Médicos, Residentes,
  Internos, Policías, Técnicos — datos de ejemplo estáticos.
- Tarjeta con el total de raciones servidas hoy vs. raciones previstas para el turno actual.

## Sección 3 — Importar Excel

- Input de archivo que acepte `.xlsx`, estilizado como zona de carga (no el botón nativo del
  navegador — ver la sección de Calidad visual).
- Lee el archivo con SheetJS y muestra una tabla de vista previa con las primeras filas.

## Calidad visual (obligatorio, no negociable)

Este punto es crítico — un intento anterior de un prototipo relacionado quedó con controles
nativos del navegador sin estilizar (el botón "Choose File" por defecto), lo cual no es
aceptable para este mockup, que representa la aplicación real frente a la jefa de nutrición.

- Ningún control de formulario nativo (inputs, botones, especialmente `input type="file"`)
  puede quedar visible sin estilizar. El input de archivo real se oculta y se reemplaza
  visualmente por un componente propio con el mismo lenguaje visual del resto de la app.
- Todo botón: color de acento del sistema, estado `:hover` distinto, transición suave, cursor
  pointer.
- Paleta de colores consistente en las cuatro secciones del sidebar (incluyendo la
  deshabilitada) y en el header — no introducir colores nuevos sin razón.
- La persona que usará esta app (la jefa de nutrición) no es necesariamente técnica: prioriza
  texto legible (tamaños de fuente generosos), iconos claros, y una interfaz que no se sienta
  recargada.

## Qué revisar antes de dar por terminado el mockup

- La app corre con `npm run dev` sin errores ni warnings en la consola del navegador.
- Componentización sensata: cada sección del sidebar es su propio componente, no todo
  amontonado en un solo archivo `App.jsx`.
- Ningún control se ve con el estilo por defecto del navegador.
- Cambiar de sección en el sidebar y volver a "Pantalla en vivo" no reinicia el contador de
  raciones (el estado vive en el componente padre, no en cada sección individual).
- El ítem "Pacientes" del sidebar se ve visualmente distinto (deshabilitado) del resto, sin
  romper el layout.
