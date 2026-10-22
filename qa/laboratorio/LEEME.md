# Laboratorio QA

La API real del comedor con un reloj movible y un panel para simular el lector
biométrico. Sirve para probar a mano cualquier caso en segundos, viendo el
resultado en la app de verdad.

## Arrancar

Desde la raíz de `wt-qa`, en PowerShell:

```powershell
.\qa\laboratorio\iniciar.ps1            # base real de desarrollo: bd_nutricion + bd_proyecto_backend
.\qa\laboratorio\iniciar.ps1 -Base sim  # base sintética: bd_nutricion_escenario_sim + bd_turnos_escenario_demo
```

Hace todo solo:

1. Cierra laboratorios o fronts anteriores de este worktree (nunca procesos ajenos).
2. Abre dos ventanas: «Laboratorio QA - API» (puerto 8000) y «Laboratorio QA - Front» (5173).
3. Abre la app en el navegador: http://localhost:5173

El laboratorio es un **modal dentro de la app**: botón «Laboratorio QA» abajo a
la izquierda, o `Ctrl+Shift+L`. El botón lo inyecta `front.mjs` al servir la
app; no existe en `comedorfront/src`.

Para detener, cierra las dos ventanas. Si MySQL tiene contraseña:
`$env:DB_PASSWORD = '...'` antes de arrancar.

## Probar un caso

1. **Reloj**: elige una comida (Desayuno, Almuerzo, Té, Cena) o un día de la
   lista «Días con turnos». En la base real solo hay comidas asignadas en
   agosto de 2026: empieza por ahí.
2. **Casos en un clic**: Entrega normal, Duplicado, Sin derecho, Huella no
   reconocida o Fuera de horario. El panel elige a la persona adecuada y el
   servidor decide el resultado con las mismas reglas que en producción.
3. **Mira la app**: entra como cocinera en http://localhost:5173 y revisa
   Control Biométrico. Para la huella no reconocida, ábrela e identifica a la
   persona. Como jefa, revisa Supervisión.
4. **Limpiar** borra solo lo que creó el laboratorio.

También puedes marcar la huella de una persona concreta desde **Padrón**.

¿No recuerdas una contraseña? En **Cuentas de acceso**, «Clave temporal» genera
una nueva (se muestra una vez) y quita el bloqueo por intentos fallidos.

## Qué toca y qué no

- Las lecturas pasan por `registrar_marcacion()`, la lógica real. Nada se decide en el panel.
- Escribe solo en la base propia y marca todo con el dispositivo `laboratorio-qa`.
  La base de turnos se lee por las vistas `v_*` y nunca se escribe.
- El reloj movido es el de negocio (`reloj.ahora`). El de seguridad (tokens,
  bloqueo de login) sigue siendo el real, así que la sesión no caduca por mover la hora.
- Las rutas `/_lab` existen solo cuando se arranca con este script: no hay
  nada del laboratorio dentro de `comedorback/app` ni de `comedorfront/src`.
